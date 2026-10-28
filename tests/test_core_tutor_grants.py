"""Grant validity (SPEC §a.3, §e.1, §e.4 "Grants"; ADR-T02; SC-3, CB-4, CB-5; PLAN T05).

The expected side of every test is parsed from ``docs/tutoring/SPEC.md``: the
``GrantStatus`` literal, the ``GrantFacts`` fields and the signatures from §e.1,
the enum values from §a.1, and the precedence comment under ``grant_status``,
which becomes an oracle that never calls the module under test (PLAN §0.8, "no
self-comparison").
"""

from __future__ import annotations

import inspect
import itertools
import re
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

from lemely.core import tutor_grants
from lemely.core.tutor_grants import GrantFacts, GrantStatus, grant_is_valid, grant_status

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEXT = (ROOT / "docs" / "tutoring" / "SPEC.md").read_text(encoding="utf-8")


def _between(start_marker: str, end_marker: str) -> str:
    start = SPEC_TEXT.index(start_marker)
    return SPEC_TEXT[start : SPEC_TEXT.index(end_marker, start)]


_E1_GRANTS = _between("# lemely/core/tutor_grants.py", "# lemely/core/tutor_outcomes.py")


def _spec_enum(pg_type: str) -> tuple[str, ...]:
    for line in _between("### a.1 Enum types", "**Additive values").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == f"`{pg_type}`":
            return tuple(re.findall(r"`(\w+)`", cells[1]))
    raise AssertionError(f"SPEC §a.1 has no {pg_type} row")


def _split_top_level(text: str) -> list[str]:
    parts, current, depth = [], [], 0
    for char in text:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _spec_precedence() -> tuple[dict[str, str], list[str], frozenset[str]]:
    """The ``grant_status`` precedence comment of §e.1.

    Returns the revoke-reason -> status map, the statuses that follow it in
    order, and the listing states the ``tutor_unavailable`` step allows.
    """
    match = re.search(r"# precedence: (.*?)\ndef ", _E1_GRANTS, re.S)
    assert match, "SPEC §e.1 grant_status has no precedence comment"
    text = " ".join(line.strip().lstrip("#").strip() for line in match.group(1).splitlines())
    head, *rest = _split_top_level(text)
    reasons = re.fullmatch(r"revoke_reason \((.*)\)", head)
    assert reasons, head
    revoked: dict[str, str] = {}
    for part in _split_top_level(reasons.group(1)):
        reason, _, status = part.partition("->")
        revoked[reason.strip()] = (status or reason).strip()
    order = []
    allowed: frozenset[str] = frozenset()
    for item in rest:
        word = re.match(r"\w+", item)
        assert word, item
        order.append(word.group(0))
        if listing := re.search(r"listing_state not in \{([^}]*)\}", item):
            allowed = frozenset(state.strip() for state in listing.group(1).split(","))
    return revoked, order, allowed


LISTING_STATES = _spec_enum("tutorlistingstate")
REVOKE_REASONS = _spec_enum("grantrevokereason")
REVOKED_STATUS, PRECEDENCE, GRANT_LISTING_STATES = _spec_precedence()

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
CREATED = NOW - timedelta(days=30)
SECOND = timedelta(seconds=1)
EXPIRIES: dict[str, datetime | None] = {
    "never": None,
    "later": NOW + timedelta(days=1),
    "passed": NOW - timedelta(days=1),
}


def _facts(
    *,
    reason: str | None = None,
    expires_at: datetime | None = None,
    blocked: bool = False,
    listing: str = "listed",
) -> GrantFacts:
    return GrantFacts(
        created_at=CREATED,
        revoked_at=None if reason is None else NOW - timedelta(days=2),
        revoke_reason=reason,
        expires_at=expires_at,
        tutor_listing_state=listing,
        blocked=blocked,
    )


def _oracle(facts: GrantFacts, now: datetime) -> str:
    """``grant_status`` read straight off the SPEC precedence comment."""
    if facts.revoke_reason is not None:
        return REVOKED_STATUS[facts.revoke_reason]
    holds = {
        "expired": facts.expires_at is not None and now >= facts.expires_at,
        "blocked": facts.blocked,
        "tutor_unavailable": facts.tutor_listing_state not in GRANT_LISTING_STATES,
        "active": True,
    }
    assert set(holds) == set(PRECEDENCE), PRECEDENCE
    return next(status for status in PRECEDENCE if holds[status])


# --- the module matches SPEC §a.1 and §e.1 -------------------------------------------------


def test_spec_parsers_find_the_precedence_and_enums() -> None:
    assert len(LISTING_STATES) == 6
    assert set(REVOKED_STATUS) == set(REVOKE_REASONS)
    assert len(REVOKE_REASONS) == 4
    assert PRECEDENCE[-1] == "active"
    assert GRANT_LISTING_STATES
    assert set(LISTING_STATES) > GRANT_LISTING_STATES
    assert set(REVOKED_STATUS.values()) | set(PRECEDENCE) == set(get_args(GrantStatus))


def test_grant_status_literal_matches_spec_e1() -> None:
    match = re.search(r"^GrantStatus = Literal\[(.*?)\]", _E1_GRANTS, re.M | re.S)
    assert match
    expected = tuple(re.findall(r'"(\w+)"', match.group(1)))
    assert len(expected) == 7
    assert get_args(GrantStatus) == expected


def test_grant_facts_fields_match_spec_e1() -> None:
    match = re.search(r"^class GrantFacts:(.*?)(?=^def )", _E1_GRANTS, re.M | re.S)
    assert match
    expected = re.findall(r"(\w+): ", match.group(1))
    assert len(expected) == 6
    assert [field.name for field in fields(GrantFacts)] == expected
    assert GrantFacts.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "__slots__" in vars(GrantFacts)


def test_public_signatures_match_spec_e1() -> None:
    spec = {
        match.group(1): (match.group(2), match.group(3).strip())
        for match in re.finditer(r"^def (\w+)\((.*?)\) -> ([^#\n]+)", _E1_GRANTS, re.M)
    }
    assert set(spec) == {"grant_status", "grant_is_valid"}
    for name, (params, returns) in spec.items():
        signature = inspect.signature(getattr(tutor_grants, name))
        expected, keyword_only = [], False
        for part in _split_top_level(params):
            if part == "*":
                keyword_only = True
                continue
            expected.append((part, keyword_only))
        got = [
            (parameter.name, parameter.kind is inspect.Parameter.KEYWORD_ONLY)
            for parameter in signature.parameters.values()
        ]
        assert got == expected, name
        assert signature.return_annotation == returns, name


# --- the truth table ------------------------------------------------------------------------


def test_grant_status_truth_table_with_precedence() -> None:
    rows = list(itertools.product((None, *REVOKE_REASONS), EXPIRIES, (False, True), LISTING_STATES))
    assert len(rows) == (1 + len(REVOKE_REASONS)) * len(EXPIRIES) * 2 * len(LISTING_STATES)
    assert len(rows) == 180
    seen = set()
    for reason, expiry, blocked, listing in rows:
        facts = _facts(reason=reason, expires_at=EXPIRIES[expiry], blocked=blocked, listing=listing)
        expected = _oracle(facts, NOW)
        assert grant_status(facts, now=NOW) == expected, (reason, expiry, blocked, listing)
        assert grant_is_valid(facts, now=NOW) is (expected == "active"), (reason, expiry, listing)
        seen.add(expected)
    assert seen == set(get_args(GrantStatus))


def test_grant_invalid_when_listing_rejected() -> None:
    # CB-4: a re-review that ends in ``rejected`` ends the grant at the next read.
    assert "rejected" in LISTING_STATES
    rejected = _facts(listing="rejected")
    assert grant_status(rejected, now=NOW) == "tutor_unavailable"
    assert not grant_is_valid(rejected, now=NOW)
    for listing in LISTING_STATES:
        facts = _facts(listing=listing)
        assert grant_is_valid(facts, now=NOW) is (listing in GRANT_LISTING_STATES), listing


def test_grant_valid_while_pending_review_or_paused() -> None:
    # SC-3: editing a moderated field sends the profile back to review; grants stay valid.
    assert grant_status(_facts(listing="pending_review"), now=NOW) == "active"
    # Pausing is ``paused_at``, orthogonal to the listing state, and GrantFacts has
    # no input for it: a paused listed tutor is "listed" here, so the grant holds.
    assert not [field.name for field in fields(GrantFacts) if "pause" in field.name]
    assert grant_is_valid(_facts(listing="listed"), now=NOW)


def test_reinstatement_does_not_restore_grant_status() -> None:
    # CB-5: a suspension revokes every live grant in its transaction; A3 reinstates
    # the listing but restores nothing.
    suspended = _facts(reason="tutor_suspended", listing="suspended")
    reinstated = replace(suspended, tutor_listing_state="listed")
    assert grant_status(suspended, now=NOW) == "tutor_suspended"
    assert grant_status(reinstated, now=NOW) == "tutor_suspended"
    assert not grant_is_valid(reinstated, now=NOW)
    # The same holds for every revoke reason whatever happens to the tutor or the
    # block afterwards (an unblock does not bring a block-revoked grant back).
    for reason, listing, blocked in itertools.product(
        REVOKE_REASONS, LISTING_STATES, (False, True)
    ):
        facts = _facts(reason=reason, listing=listing, blocked=blocked)
        assert grant_status(facts, now=NOW) == REVOKED_STATUS[reason], (reason, listing)
        assert not grant_is_valid(facts, now=NOW)


def test_grant_expiry_is_half_open() -> None:
    expires = NOW + timedelta(days=3)
    facts = _facts(expires_at=expires)
    assert grant_status(facts, now=expires - SECOND) == "active"
    assert grant_status(facts, now=expires) == "expired"
    assert not grant_is_valid(facts, now=expires)


def test_grant_status_compares_instants_across_zones() -> None:
    cairo = ZoneInfo("Africa/Cairo")
    expires = NOW + timedelta(days=3)
    facts = _facts(expires_at=expires.astimezone(cairo))
    assert grant_status(facts, now=expires - SECOND) == "active"
    assert grant_status(facts, now=expires.astimezone(cairo)) == "expired"


def test_grant_expiry_in_the_repeated_hour() -> None:
    # Cairo repeats 23:00-24:00 on 2026-10-29. Two instants sharing a tzinfo
    # compare by wall time in Python, ignoring fold: 23:15 (second pass, 21:15Z)
    # is after 23:30 (first pass, 20:30Z).
    cairo = ZoneInfo("Africa/Cairo")
    expires = datetime(2026, 10, 29, 23, 30, tzinfo=cairo)
    now = datetime(2026, 10, 29, 23, 15, tzinfo=cairo, fold=1)
    assert now.astimezone(UTC) > expires.astimezone(UTC)
    facts = replace(_facts(), created_at=expires - timedelta(days=30), expires_at=expires)
    assert grant_status(facts, now=now) == "expired"


# --- facts the database CHECKs refuse can only come from a bug ------------------------------


@pytest.mark.parametrize(
    "facts",
    [
        pytest.param(replace(_facts(), revoked_at=NOW), id="revoked_at-without-reason"),
        pytest.param(replace(_facts(reason="student"), revoked_at=None), id="reason-without-time"),
        pytest.param(_facts(reason="admin"), id="unknown-revoke-reason"),
        pytest.param(_facts(listing="paused"), id="unknown-listing-state"),
        pytest.param(_facts(expires_at=CREATED), id="expires-not-after-created"),
        pytest.param(
            replace(_facts(reason="student"), revoked_at=CREATED - SECOND),
            id="revoked-before-created",
        ),
        pytest.param(replace(_facts(), created_at=datetime(2026, 10, 1)), id="naive-created"),
    ],
)
def test_inconsistent_facts_refused(facts: GrantFacts) -> None:
    with pytest.raises(ValueError):
        grant_status(facts, now=NOW)
    with pytest.raises(ValueError):
        grant_is_valid(facts, now=NOW)


def test_naive_now_refused() -> None:
    with pytest.raises(ValueError):
        grant_status(_facts(), now=datetime(2026, 11, 10, 12, 0))
