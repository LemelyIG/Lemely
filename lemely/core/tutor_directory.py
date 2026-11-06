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

from lemely.core.contact_patterns import find_contact_details

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

# Letters (category Lo) that render as nothing: the Hangul fillers. A name made of, or
# padded with, one of these looks blank or looks shorter than it is.
_INVISIBLE_LETTERS: Final = frozenset({"\U0000115f", "\U00001160", "\U00003164", "\U0000ffa0"})

# Combining marks allowed on one base letter. Arabic needs two (shadda plus a vowel);
# a stack of more than that is the "zalgo" trick that hides or garbles a name.
_MAX_MARKS_PER_LETTER: Final = 2

# Uppercase, lowercase, titlecase and other letters. Not Lm (modifier letters such as a
# superscript h), which look like a letter but are not one.
_INITIAL_CATEGORIES: Final = frozenset({"Lu", "Ll", "Lt", "Lo"})


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
    combining marks (Arabic diacritics, at most two on one letter), single
    separators only (space U+0020, hyphen, apostrophe ASCII or U+2019, never two
    in a row); it must begin with a letter and end with a letter or mark. That
    excludes digits in any script, punctuation that forms URLs, emails and
    handles (``. / : @``), control characters, and every invisible or direction
    character (bidi controls, zero-width characters), which are format
    characters and not letters; the Hangul filler letters, which are letters that
    render blank, are refused by name. Last initial: ``None`` or exactly one
    uppercase, lowercase, titlecase or caseless letter (so not a modifier letter
    and not a filler).
    """
    if not 1 <= len(first_name) <= _MAX_FIRST_NAME_LENGTH:
        raise InvalidPublicNameError("first name must be 1 to 40 characters")
    previous = ""
    marks_in_a_row = 0
    for char in first_name:
        if char in _INVISIBLE_LETTERS:
            raise InvalidPublicNameError("first name contains an invisible letter")
        kind = unicodedata.category(char)[0]
        if kind == "M":
            # A mark decorates the letter before it: it needs one, and at most two.
            if unicodedata.category(previous or " ")[0] not in "LM":
                raise InvalidPublicNameError("first name has a combining mark with no letter")
            marks_in_a_row += 1
            if marks_in_a_row > _MAX_MARKS_PER_LETTER:
                raise InvalidPublicNameError("first name has too many combining marks")
        else:
            marks_in_a_row = 0
            if kind != "L" and char not in _FIRST_NAME_PUNCTUATION:
                raise InvalidPublicNameError("first name may only contain letters, spaces, - and '")
            if char in _FIRST_NAME_PUNCTUATION and previous in _FIRST_NAME_PUNCTUATION:
                raise InvalidPublicNameError("first name has two separators in a row")
        previous = char
    # A name starts with a letter (never a bare combining mark) and ends with a letter or
    # a mark (Arabic names often end in a diacritic).
    if unicodedata.category(first_name[0])[0] != "L" or (
        unicodedata.category(first_name[-1])[0] not in "LM"
    ):
        raise InvalidPublicNameError("first name must start and end with a letter")
    if last_initial is not None and not _is_initial(last_initial):
        raise InvalidPublicNameError("last initial must be a single letter")


def _is_initial(value: str) -> bool:
    """One cased or caseless letter (Lu, Ll, Lt, Lo): not a modifier letter, not a filler."""
    return (
        len(value) == 1
        and unicodedata.category(value) in _INITIAL_CATEGORIES
        and value not in _INVISIBLE_LETTERS
    )


def student_label(display_name: str | None, user_id: uuid.UUID) -> str:
    """The name a tutor sees for a student: the cleaned display name, else a stable alias.

    The alias is ``"Student "`` plus the first four hex characters of
    ``sha256(str(user_id))`` upper-cased: stable for one student, unlinkable to
    the account without the id, and never an email address (F12). The display
    name is first stripped of format characters (bidi controls, zero-width
    characters) and trimmed. It is then unusable, and the alias is used instead,
    if it is empty, contains ``@`` (after Unicode compatibility folding, so the
    fullwidth ``@`` counts), or carries any contact detail: students sometimes
    type their email or phone number into the name field and that must not reach
    a tutor.
    """
    name = "".join(c for c in (display_name or "") if unicodedata.category(c) != "Cf").strip()
    if name and "@" not in unicodedata.normalize("NFKC", name) and not find_contact_details(name):
        return name
    digest = hashlib.sha256(str(user_id).encode("ascii")).hexdigest()
    return f"Student {digest[:4].upper()}"


def zone_label(zone: str) -> str:
    """A tutor-zone name for display: ``"Africa/Cairo"`` becomes ``"Cairo time"``."""
    place = zone.strip().rsplit("/", 1)[-1].replace("_", " ").strip()
    if not place:
        raise ValueError(f"cannot label an empty zone: {zone!r}")
    return f"{place} time"
