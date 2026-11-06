"""Cross-module pins for the tutoring core (PLAN §1.4 #11; SPEC §a.1-§a.4, §e.1; F20).

``lemely.core`` may not import ``lemely.db`` (import-linter), so the literals
the pure modules write out are pinned here against independent sources: the
migration text (read with ``ast``), the ORM ``Table`` objects, the SPEC text,
the shared SQL predicates, the Python enums and the API literals. The expected
side of every assertion is read from one of those sources, never written in
this file.
"""

from __future__ import annotations

import ast
import operator
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint

from lemely.core import booking
from lemely.core.history import GRADE_ORDER
from lemely.core.tutor_grants import GrantFacts, GrantStatus, grant_is_valid, grant_status
from lemely.core.tutor_outcomes import AttemptFacts, is_counted_session, is_outcome_eligible
from lemely.db import tutoring_predicates
from lemely.db.models.enums import (
    AttemptOrigin,
    BookingParty,
    BookingState,
    BoundarySource,
    GrantRevokeReason,
    TutorListingState,
)
from lemely.db.models.tutoring import TutorBooking
from lemely.web import schemas_tutoring

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEXT = (ROOT / "docs" / "tutoring" / "SPEC.md").read_text(encoding="utf-8")
MIGRATION_0047 = ROOT / "lemely" / "db" / "migrations" / "versions" / "0047_tutor_bookings.py"
_MIGRATION = ast.parse(MIGRATION_0047.read_text(encoding="utf-8"))

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def _between(start_marker: str, end_marker: str) -> str:
    start = SPEC_TEXT.index(start_marker)
    return SPEC_TEXT[start : SPEC_TEXT.index(end_marker, start)]


def _state_set(text: str) -> frozenset[str]:
    """The one ``state IN ('a', 'b')`` list in a SQL fragment."""
    lists = re.findall(r"\bstate IN \(([^)]*)\)", text)
    assert len(lists) == 1, text
    items = [re.fullmatch(r"'(\w+)'", item.strip()) for item in lists[0].split(",")]
    assert all(items), text
    return frozenset(item.group(1) for item in items if item)


def _enum_values(enum_cls: type[BookingState] | type[BookingParty]) -> frozenset[str]:
    return frozenset(member.value for member in enum_cls)


# --- migration text through ast ---------------------------------------------------------------


def _calls(attribute: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_MIGRATION)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    ]


def _string(node: ast.expr) -> str:
    assert isinstance(node, ast.Constant), ast.dump(node)
    assert isinstance(node.value, str), ast.dump(node)
    return node.value


def _wrapped_string(node: ast.expr, wrapper: str) -> str:
    """The string inside ``sa.text("...")`` or ``op.f("...")``."""
    assert isinstance(node, ast.Call), ast.dump(node)
    assert isinstance(node.func, ast.Attribute), ast.dump(node)
    assert node.func.attr == wrapper, ast.dump(node)
    (argument,) = node.args
    return _string(argument)


def _keyword(call: ast.Call, name: str) -> ast.expr:
    matches = [keyword.value for keyword in call.keywords if keyword.arg == name]
    assert len(matches) == 1, (name, ast.dump(call))
    return matches[0]


def _migration_booking_exclusion_wheres() -> dict[str, str]:
    found = {}
    for call in _calls("create_exclude_constraint"):
        if _string(call.args[1]) == "tutor_bookings":
            found[_string(call.args[0])] = _wrapped_string(_keyword(call, "where"), "text")
    return found


def _migration_check(name: str) -> str:
    texts = [
        _string(call.args[0])
        for call in _calls("CheckConstraint")
        if _wrapped_string(_keyword(call, "name"), "f") == name
    ]
    assert len(texts) == 1, name
    return texts[0]


def _migration_index_where(name: str) -> str:
    wheres = [
        _wrapped_string(_keyword(call, "postgresql_where"), "text")
        for call in _calls("create_index")
        if _string(call.args[0]) == name
    ]
    assert len(wheres) == 1, name
    return wheres[0]


# --- SPEC text ----------------------------------------------------------------------------------

_A2_BOOKINGS = _between("#### `tutor_bookings` (0047)", "#### `tutor_booking_notes` (0047)")


def _spec_booking_exclusion_wheres() -> dict[str, str]:
    section = _between("### a.4 Exclusion constraints", "**Test databases built")
    found = {}
    for match in re.finditer(
        r'create_exclude_constraint\(\s*"(\w+)", "(\w+)",(.*?)\n\)', section, re.S
    ):
        if match.group(2) == "tutor_bookings":
            where = re.search(r'where=sa\.text\("([^"]*)"\)', match.group(3))
            assert where, match.group(0)
            found[match.group(1)] = where.group(1)
    return found


def _spec_sentence(pattern: str) -> str:
    match = re.search(pattern, SPEC_TEXT)
    assert match, pattern
    return match.group(1)


# --- ACTIVE_STATES and CANCEL_CUTOFF (F20, row 18) ------------------------------------------


def test_active_states_pinned_to_migration_and_orm_where() -> None:
    expected_names = set(re.findall(r"excl_tutor_bookings_\w+", _A2_BOOKINGS))
    assert len(expected_names) == 2  # tutor slot and student slot (row 15c)
    sources = {
        "SPEC §a.4": _spec_booking_exclusion_wheres(),
        "migration 0047": _migration_booking_exclusion_wheres(),
        "ORM TutorBooking": {
            str(constraint.name): str(constraint.where)
            for constraint in TutorBooking.__table__.constraints
            if isinstance(constraint, ExcludeConstraint)
        },
    }
    for source, wheres in sources.items():
        assert set(wheres) == expected_names, source
        for name, where in wheres.items():
            assert _state_set(where) == booking.ACTIVE_STATES, (source, name, where)
    assert _state_set(tutoring_predicates.ACTIVE_STATES_SQL) == booking.ACTIVE_STATES
    active = _spec_sentence(r'"Active" = `\{([^}]*)\}`')
    assert frozenset(state.strip() for state in active.split(",")) == booking.ACTIVE_STATES
    assert _enum_values(BookingState) > booking.ACTIVE_STATES


_CUTOFF = re.compile(r"cancelled_at (<=|<) starts_at - interval '(\d+) (hour|day|minute)s?'")


def test_cancel_cutoff_pinned_to_late_cancel_check_text() -> None:
    orm = [
        str(constraint.sqltext)
        for constraint in TutorBooking.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
        and str(constraint.name).endswith("late_cancel_reason")
    ]
    assert len(orm) == 1
    sources = {
        "SPEC §a.2": _spec_sentence(r"- `late_cancel_reason` \(row 18\): `([^`]*)`"),
        "migration 0047": _migration_check("ck_tutor_bookings_late_cancel_reason"),
        "ORM TutorBooking": orm[0],
    }
    starts = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    for source, text in sources.items():
        found = _CUTOFF.findall(text)
        assert len(found) == 1, (source, text)
        ((comparison, amount, unit),) = found
        cutoff = timedelta(**{f"{unit}s": int(amount)})
        assert cutoff == booking.CANCEL_CUTOFF, source
        # Around the boundary the CHECK's no-reason disjunct and is_late_cancel agree.
        allows = {"<=": operator.le, "<": operator.lt}[comparison]
        for delta in (-SECOND, timedelta(0), SECOND):
            cancelled_at = starts - cutoff + delta
            late = booking.is_late_cancel(
                cancelled_by="tutor", cancelled_at=cancelled_at, starts_at=starts
            )
            assert allows(cancelled_at, starts - cutoff) is not late, (source, delta)


def test_core_booking_literals_equal_python_enums() -> None:
    states = get_args(booking.BookingStateLit)
    parties = get_args(booking.Party)
    assert len(states) == len(set(states)) == len(BookingState)
    assert frozenset(states) == _enum_values(BookingState)
    assert len(parties) == len(set(parties)) == len(BookingParty)
    assert frozenset(parties) == _enum_values(BookingParty)
    effective = get_args(booking.EffectiveState)
    assert set(effective) == set(get_args(schemas_tutoring.EffectiveStateLit))
    assert set(states) < set(effective)


# --- grants (SC-3) ------------------------------------------------------------------------------


def _grant(*, reason: str | None = None, listing: str = "listed") -> GrantFacts:
    return GrantFacts(
        created_at=NOW - timedelta(days=30),
        revoked_at=None if reason is None else NOW - timedelta(days=1),
        revoke_reason=reason,
        expires_at=None,
        tutor_listing_state=listing,
        blocked=False,
    )


def test_grant_status_literal_equals_api_literal() -> None:
    statuses = get_args(GrantStatus)
    assert len(statuses) == len(set(statuses)) == 7
    assert set(statuses) == set(get_args(schemas_tutoring.GrantStatusLit))


def test_grant_inputs_cover_python_enums() -> None:
    statuses = set(get_args(GrantStatus))
    revoked = set()
    for reason in GrantRevokeReason:
        facts = _grant(reason=reason.value)
        revoked.add(grant_status(facts, now=NOW))
        assert not grant_is_valid(facts, now=NOW), reason
    assert revoked <= statuses
    assert len(revoked) == len(GrantRevokeReason)  # each reason has its own status
    by_listing = {
        listing.value: grant_status(_grant(listing=listing.value), now=NOW)
        for listing in TutorListingState
    }
    assert set(by_listing.values()) <= statuses
    assert len(by_listing) == 6


# --- outcomes (ADR-T04) -------------------------------------------------------------------------


def test_outcome_membership_pinned_to_predicate_index_and_spec() -> None:
    counted = frozenset(
        state.value
        for state in BookingState
        if is_counted_session(state=state.value, accepted_at=NOW, ends_at=NOW, now=NOW)
    )
    assert counted
    assert not any(
        is_counted_session(state=state.value, accepted_at=None, ends_at=NOW, now=NOW)
        for state in BookingState
    )
    orm_where = [
        str(index.dialect_options["postgresql"]["where"])
        for index in TutorBooking.__table__.indexes
        if index.name == "ix_tutor_bookings_outcome_cohort"
    ]
    assert len(orm_where) == 1
    with_time = {
        "predicate OUTCOME_MEMBERSHIP_SQL": tutoring_predicates.OUTCOME_MEMBERSHIP_SQL,
        "SPEC §a.3": _spec_sentence(
            r"Membership of a tutor's outcome cohort is decided by `([^`]*)`"
        ),
        "SPEC §e.3 cohort": _spec_sentence(
            r"\*Cohort:\* per \(subject, student\) from `tutor_bookings` where `([^`]*)`"
        ),
    }
    index_only = {
        "SPEC §a.2 index": _spec_sentence(
            r"`ix_tutor_bookings_outcome_cohort` on `[^`]*` WHERE `([^`]*)`"
        ),
        "migration 0047 index": _migration_index_where("ix_tutor_bookings_outcome_cohort"),
        "ORM index": orm_where[0],
    }
    for source, text in {**with_time, **index_only}.items():
        assert _state_set(text) == counted, (source, text)
        assert "accepted_at IS NOT NULL" in text, source
    for source, text in with_time.items():
        assert "ends_at <= now()" in text, source
    assert is_counted_session(state="no_show", accepted_at=NOW, ends_at=NOW, now=NOW)
    assert not is_counted_session(state="no_show", accepted_at=NOW, ends_at=NOW + SECOND, now=NOW)


def test_outcome_eligibility_literals_are_python_enum_values() -> None:
    e1 = _between("# lemely/core/tutor_outcomes.py", "# lemely/core/contact_patterns.py")
    match = re.search(r'origin == "(\w+)", grade on the ladder, boundary_source == "(\w+)"', e1)
    assert match
    origin, boundary = match.groups()
    assert origin in {member.value for member in AttemptOrigin}
    assert boundary in {member.value for member in BoundarySource}

    def eligible(origin_value: str, boundary_value: str) -> bool:
        facts = AttemptFacts(
            origin=origin_value,
            grade=GRADE_ORDER[0],
            boundary_source=boundary_value,
            subject_code="0625",
            deleted=False,
        )
        return is_outcome_eligible(facts, subject_code="0625", ladder=GRADE_ORDER)

    assert {o.value for o in AttemptOrigin if eligible(o.value, boundary)} == {origin}
    assert {b.value for b in BoundarySource if eligible(origin, b.value)} == {boundary}
    assert len(AttemptOrigin) == 3
    assert len(BoundarySource) == 3
