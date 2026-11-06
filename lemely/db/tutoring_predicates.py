"""The tutoring SQL predicates, written once (SPEC ``docs/tutoring/SPEC.md`` §a.3, PLAN §1.4 #9).

Every list, count and filter in the tutoring repositories builds its
``WHERE`` clause from these fragments rather than restating them, so a
directory query, a booking list and an outcome cohort can never disagree about
what "listed", "blocked", "live pending" or "awaiting outcome" means (F6, O11).
``tests/test_tutoring_predicates_single_source.py`` enforces the block half of
that: no module outside its allowlist may name ``tutoring_blocks`` or
``TutoringBlock``.

Two kinds of fragment:

* **Booking-state constants** (:data:`EFFECTIVE_STATE_SQL`,
  :data:`ACTIVE_STATES_SQL`, :data:`LIVE_PENDING_SQL`,
  :data:`OUTCOME_MEMBERSHIP_SQL`) name ``tutor_bookings`` columns
  unqualified (``state``, ``starts_at``, ``ends_at``, ``accepted_at``). Use them
  where those names resolve to ``tutor_bookings`` unambiguously: a statement
  over ``tutor_bookings`` joined to ``tutor_profiles``, ``users`` or
  ``subjects`` qualifies (none of those has such a column). Each is wrapped in
  parentheses so it composes with ``AND``/``OR`` safely.
* **Builders** take the column or bind parameter to compare and return a
  fragment. The block builders accept only a table-qualified column
  (``tp.user_id``) or a named bind parameter (``:caller_id``): an unqualified
  name such as ``removed_at`` would bind to the subquery's own
  ``tutoring_blocks`` row and silently match. Anything else raises
  :class:`ValueError`, so a builder can never splice caller text into SQL.

Every time comparison uses the database ``now()`` (SPEC §0: no app clock in a
guard), which inside a transaction is that transaction's start time.

These are plain SQL strings for ``sqlalchemy.text`` statements. Values are only
ever bound as parameters.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

#: One fragment per effective booking state (SPEC §a.3 "Derived read-time
#: states"). ``awaiting_outcome`` and the read-time half of ``expired`` are
#: never stored; every other state is its stored value. Exactly one fragment is
#: true for any row (``tests/test_db_tutoring_schema.py`` proves the partition).
EFFECTIVE_STATE_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "requested": "(state = 'requested' AND starts_at > now())",
        "accepted": "(state = 'accepted' AND ends_at > now())",
        "awaiting_outcome": "(state = 'accepted' AND ends_at <= now())",
        "declined": "(state = 'declined')",
        "cancelled": "(state = 'cancelled')",
        "completed": "(state = 'completed')",
        "no_show": "(state = 'no_show')",
        "expired": "(state = 'expired' OR (state = 'requested' AND starts_at <= now()))",
    }
)

#: "Active" = holds a slot: the exact predicate of both booking exclusion
#: constraints (SPEC §a.3), pinned to ``core.booking.ACTIVE_STATES``.
ACTIVE_STATES_SQL: Final = "(state IN ('requested', 'accepted'))"

#: A request still awaiting the tutor: counted against
#: ``MAX_PENDING_PER_STUDENT`` and listed as pending (SPEC §a.3, §a.4b).
LIVE_PENDING_SQL: Final = EFFECTIVE_STATE_SQL["requested"]

#: Membership of a tutor's outcome cohort (ADR-T04, SPEC §a.3 "Outcome marks do
#: not move outcome figures"): marking a session completed or no-show, a block
#: or a dispute never changes it.
OUTCOME_MEMBERSHIP_SQL: Final = (
    "(accepted_at IS NOT NULL AND state IN ('accepted', 'completed', 'no_show') "
    "AND ends_at <= now())"
)

_IDENTIFIER: Final = r"[A-Za-z_][A-Za-z0-9_]*"
#: ``alias.column`` or ``:bind``. Deliberately no bare ``column``: inside the
#: block subqueries a bare name resolves against ``tutoring_blocks`` first.
_QUALIFIED_OR_PARAM: Final = re.compile(rf"{_IDENTIFIER}\.{_IDENTIFIER}|:{_IDENTIFIER}")
_ALIAS: Final = re.compile(_IDENTIFIER)

#: Alias of ``tutoring_blocks`` inside the block subqueries. A caller argument
#: qualified with it would be captured by the subquery, so it is refused.
_BLOCK_ALIAS: Final = "tutoring_block_pred"


def _operand(value: str, *, name: str) -> str:
    """Return ``value`` if it is a table-qualified column or a named bind parameter."""
    if not _QUALIFIED_OR_PARAM.fullmatch(value):
        raise ValueError(
            f"{name} must be a qualified column (alias.column) or a :bind parameter, got {value!r}"
        )
    if value.split(".", 1)[0] == _BLOCK_ALIAS:
        raise ValueError(f"{name} may not use the reserved alias {_BLOCK_ALIAS!r}")
    return value


def listed_and_not_paused_sql(profile_alias: str) -> str:
    """Directory visibility of a ``tutor_profiles`` row aliased ``profile_alias`` (SPEC §a.3).

    ``listing_state = 'listed' AND paused_at IS NULL``: the same condition new
    bookings and new grants require.
    """
    if not _ALIAS.fullmatch(profile_alias) or profile_alias == _BLOCK_ALIAS:
        raise ValueError(f"profile_alias must be a plain SQL alias, got {profile_alias!r}")
    return f"({profile_alias}.listing_state = 'listed' AND {profile_alias}.paused_at IS NULL)"


def active_block_between_sql(student_user_col: str, tutor_user_col: str) -> str:
    """True when an active block exists between the pair, in either direction (O11).

    Both operands are ``users.id`` values: the tutor side is
    ``tutor_profiles.user_id``, **never** ``tutor_profiles.id``, because blocks
    are keyed on users (SPEC §a.2 ``tutoring_blocks``). Active means
    ``removed_at IS NULL``.
    """
    student = _operand(student_user_col, name="student_user_col")
    tutor = _operand(tutor_user_col, name="tutor_user_col")
    b = _BLOCK_ALIAS
    return (
        f"(EXISTS (SELECT 1 FROM tutoring_blocks {b} WHERE {b}.removed_at IS NULL AND ("  # noqa: S608 - operands validated above
        f"({b}.blocker_user_id = {student} AND {b}.blocked_user_id = {tutor}) OR "
        f"({b}.blocker_user_id = {tutor} AND {b}.blocked_user_id = {student}))))"
    )


def active_block_since_sql(student_user_col: str, tutor_user_col: str) -> str:
    """When the pair's active block began, or NULL when none is active (SC-11, SPEC §i.8).

    The earliest ``updated_at`` among the active blocks between the pair, in either
    direction; NULL exactly when :func:`active_block_between_sql` is false. A block row
    is written when it is made, lifted (``removed_at`` set) or renewed (``removed_at``
    cleared), each time with ``updated_at = now()``, so an active row's ``updated_at``
    is the instant it last became active. ``created_at`` would name the first block,
    which a lifted and renewed block outlives. Operands are ``users.id`` values, as in
    :func:`active_block_between_sql`.
    """
    student = _operand(student_user_col, name="student_user_col")
    tutor = _operand(tutor_user_col, name="tutor_user_col")
    b = _BLOCK_ALIAS
    return (
        f"(SELECT min({b}.updated_at) FROM tutoring_blocks {b} WHERE {b}.removed_at IS NULL "  # noqa: S608 - operands validated above
        f"AND (({b}.blocker_user_id = {student} AND {b}.blocked_user_id = {tutor}) OR "
        f"({b}.blocker_user_id = {tutor} AND {b}.blocked_user_id = {student})))"
    )


def student_ever_blocked_tutor_sql(student_user_col: str, tutor_user_col: str) -> str:
    """True when the student has ever blocked the tutor's user, removed blocks included.

    Directional (student -> tutor only) and blind to ``removed_at``: a student
    who ever blocked a tutor never counts in that tutor's outcome figures
    (ADR-T04, SPEC §e.3 cohort). Operands are ``users.id`` values, as in
    :func:`active_block_between_sql`.
    """
    student = _operand(student_user_col, name="student_user_col")
    tutor = _operand(tutor_user_col, name="tutor_user_col")
    b = _BLOCK_ALIAS
    return (
        f"(EXISTS (SELECT 1 FROM tutoring_blocks {b} "  # noqa: S608 - operands validated above
        f"WHERE {b}.blocker_user_id = {student} AND {b}.blocked_user_id = {tutor}))"
    )


def student_block_of_tutor_created_at_sql(student_user_col: str, tutor_user_col: str) -> str:
    """The ``created_at`` of the student's block of the tutor's user, or NULL.

    Removed blocks count. Rows are never deleted and a re-block keeps
    ``created_at``, so this is the first block (ADR-T04 hold, SC-13d).
    """
    student = _operand(student_user_col, name="student_user_col")
    tutor = _operand(tutor_user_col, name="tutor_user_col")
    b = _BLOCK_ALIAS
    return (
        f"(SELECT min({b}.created_at) FROM tutoring_blocks {b} "  # noqa: S608 - operands validated above
        f"WHERE {b}.blocker_user_id = {student} AND {b}.blocked_user_id = {tutor})"
    )


__all__ = [
    "ACTIVE_STATES_SQL",
    "EFFECTIVE_STATE_SQL",
    "LIVE_PENDING_SQL",
    "OUTCOME_MEMBERSHIP_SQL",
    "active_block_between_sql",
    "active_block_since_sql",
    "listed_and_not_paused_sql",
    "student_block_of_tutor_created_at_sql",
    "student_ever_blocked_tutor_sql",
]
