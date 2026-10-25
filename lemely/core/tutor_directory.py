"""Directory helpers: availability filter, public names, student labels, zone labels.

Everything here is a small pure rule that the directory repository, the booking
routes and the DTO builders must agree on, kept out of SQL and out of routers so
there is one definition and a test that can fail it (SPEC section e.1).

* :func:`rule_matches` is the Python twin of the SQL availability filter; a
  parity test (SPEC section e.4, F6) evaluates both over a generated table.
* :func:`validate_public_name` is the full allowlist behind the two coarse DB
  CHECKs on ``tutor_profiles.public_first_name`` (SC-25): a tutor's first name is
  the one piece of personal data that is public on the open web, so it must be a
  name and nothing a browser could render as something else.
* :func:`student_label` is the only way a student's name reaches a tutor (F12).
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import TYPE_CHECKING, Final, Literal, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

TimeOfDay = Literal["morning", "afternoon", "evening"]

# Tutor-zone wall clock as minutes after midnight, half-open [start, end):
# morning 06:00-12:00, afternoon 12:00-17:00, evening 17:00-22:00 (SPEC section b.2, SP1).
TIME_OF_DAY_MINUTES: Final[Mapping[TimeOfDay, tuple[int, int]]] = {
    "morning": (360, 720),
    "afternoon": (720, 1020),
    "evening": (1020, 1320),
}

# ``tutor_profiles.public_first_name`` is varchar(40) (SPEC section a.2).
_MAX_FIRST_NAME_LENGTH: Final = 40

_FIRST_NAME_PUNCTUATION: Final = frozenset({" ", "-", "'", "\U00002019"})


class InvalidPublicNameError(ValueError):
    """A tutor's public first name or last initial is outside the SC-25 allowlist."""


class AvailabilityRuleLike(Protocol):
    """The three fields of a weekly availability rule that :func:`rule_matches` reads.

    Structural, so the pure booking module's ``AvailabilityRule`` satisfies it
    without this module importing that one.
    """

    @property
    def iso_weekday(self) -> int: ...

    @property
    def start_minute(self) -> int: ...

    @property
    def end_minute(self) -> int: ...


def rule_matches(
    rule: AvailabilityRuleLike, days: frozenset[int], times: frozenset[TimeOfDay]
) -> bool:
    """Whether one weekly rule satisfies a directory availability filter.

    ``days`` holds ISO weekdays (Monday 1 .. Sunday 7) and ``times`` holds
    time-of-day buckets. An empty set means that dimension is not filtered, so
    ``rule_matches(rule, frozenset(), frozenset())`` is always true. Otherwise
    the rule must fall on one of the selected days *and* overlap at least one
    selected bucket. Overlap is on half-open minute ranges, so a rule that ends
    exactly when a bucket starts (or starts exactly when it ends) does not match
    it. A tutor appears in the results if any of their rules matches.
    """
    if days and rule.iso_weekday not in days:
        return False
    if not times:
        return True
    return any(
        rule.start_minute < bucket_end and bucket_start < rule.end_minute
        for bucket_start, bucket_end in (TIME_OF_DAY_MINUTES[t] for t in times)
    )


def public_name(first_name: str, last_initial: str | None) -> str:
    """The name shown on a tutor's public card: ``"Sara M."``, or ``"Sara"`` with no initial.

    Formatting only; :func:`validate_public_name` decides what may be stored. The
    initial is upper-cased when that stays a single character (the German sharp
    s upper-cases to ``"SS"``, which would turn an initial into two letters, so
    it is kept as given).
    """
    first = first_name.strip()
    initial = (last_initial or "").strip()
    if not initial:
        return first
    upper = initial.upper()
    return f"{first} {upper if len(upper) == 1 else initial}."


def validate_public_name(first_name: str, last_initial: str | None) -> None:
    """Raise :class:`InvalidPublicNameError` unless the name fits the SC-25 allowlist.

    First name: 1 to 40 characters; Unicode letters (Arabic included) and their
    combining marks (Arabic diacritics), single spaces U+0020, hyphen, apostrophe
    (ASCII or U+2019) only; it must begin and end with a letter or mark. That
    excludes digits in any script, punctuation that forms URLs, emails and
    handles (``. / : @``), control characters, and every invisible or direction
    character (bidi controls, zero-width characters), which are format
    characters and not letters. Last initial: ``None`` or exactly one letter.
    """
    if not 1 <= len(first_name) <= _MAX_FIRST_NAME_LENGTH:
        raise InvalidPublicNameError("first name must be 1 to 40 characters")
    for char in first_name:
        category = unicodedata.category(char)
        if category[0] not in "LM" and char not in _FIRST_NAME_PUNCTUATION:
            raise InvalidPublicNameError("first name may only contain letters, spaces, - and '")
    # A name starts with a letter (never a bare combining mark) and ends with a letter or
    # a mark (Arabic names often end in a diacritic).
    if unicodedata.category(first_name[0])[0] != "L" or (
        unicodedata.category(first_name[-1])[0] not in "LM"
    ):
        raise InvalidPublicNameError("first name must start and end with a letter")
    if last_initial is not None and not (len(last_initial) == 1 and last_initial.isalpha()):
        raise InvalidPublicNameError("last initial must be a single letter")


def student_label(display_name: str | None, user_id: uuid.UUID) -> str:
    """The name a tutor sees for a student: the trimmed display name, else a stable alias.

    The alias is ``"Student "`` plus the first four hex characters of
    ``sha256(str(user_id))`` upper-cased: stable for one student, unlinkable to
    the account without the id, and never an email address (F12). A display name
    that contains ``@`` (after Unicode compatibility folding, so the fullwidth
    ``@`` counts) is treated as unusable, because students sometimes type their
    email into the name field and that must not reach a tutor.
    """
    name = (display_name or "").strip()
    if name and "@" not in unicodedata.normalize("NFKC", name):
        return name
    digest = hashlib.sha256(str(user_id).encode("ascii")).hexdigest()
    return f"Student {digest[:4].upper()}"


def zone_label(zone: str) -> str:
    """A tutor-zone name for display: ``"Africa/Cairo"`` becomes ``"Cairo time"``."""
    place = zone.strip().rsplit("/", 1)[-1].replace("_", " ").strip()
    if not place:
        raise ValueError(f"cannot label an empty zone: {zone!r}")
    return f"{place} time"
