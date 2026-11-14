"""Pure rules for the landing-page waitlist: vocabularies, validation, CSV and token hygiene.

No I/O and no framework: the DTOs, the repository and the digest all call in here, so the
rules (which subjects exist, which exam sessions are open, what a phone number looks like,
how a CSV cell is neutralised) have one home. ``web/src/lib/waitlist-api.ts`` mirrors the
vocabularies; the values below are the wire contract.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import date, timedelta
from typing import Final

ROLES: Final = ("student", "teacher", "parent", "centre_admin")
LEVELS: Final = ("o_level", "as_level", "a_level")
EXAM_BOARDS: Final = ("caie", "edexcel", "oxford_aqa", "other")
STATUSES: Final = ("new", "contacted", "invited", "declined")

#: Value to label: common Cambridge IGCSE / O-Level / AS & A-Level subjects, one entry per subject
#: name (not per syllabus code), A-Z. Listing a subject says nothing about whether Lemely marks it
#: today. Anything not here goes in free-text ``other_subjects``.
ALL_SUBJECTS: Final[dict[str, str]] = {
    "accounting": "Accounting",
    "additional_mathematics": "Additional Mathematics",
    "agriculture": "Agriculture",
    "arabic": "Arabic",
    "art_and_design": "Art & Design",
    "biology": "Biology",
    "business": "Business",
    "chemistry": "Chemistry",
    "chinese": "Chinese",
    "classical_studies": "Classical Studies",
    "computer_science": "Computer Science",
    "design_and_technology": "Design & Technology",
    "drama": "Drama",
    "economics": "Economics",
    "english": "English",
    "english_literature": "English Literature",
    "environmental_management": "Environmental Management",
    "food_and_nutrition": "Food & Nutrition",
    "french": "French",
    "further_mathematics": "Further Mathematics",
    "geography": "Geography",
    "german": "German",
    "global_perspectives": "Global Perspectives",
    "hindi": "Hindi",
    "history": "History",
    "ict": "ICT",
    "islamic_studies": "Islamic Studies",
    "italian": "Italian",
    "japanese": "Japanese",
    "latin": "Latin",
    "law": "Law",
    "marine_science": "Marine Science",
    "mathematics": "Mathematics",
    "media_studies": "Media Studies",
    "music": "Music",
    "physical_education": "Physical Education",
    "physics": "Physics",
    "portuguese": "Portuguese",
    "psychology": "Psychology",
    "religious_studies": "Religious Studies",
    "russian": "Russian",
    "sociology": "Sociology",
    "spanish": "Spanish",
    "statistics": "Statistics",
    "thinking_skills": "Thinking Skills",
    "travel_and_tourism": "Travel & Tourism",
    "urdu": "Urdu",
}

#: The eight shown first in the form, in this order; each is also in :data:`ALL_SUBJECTS`.
TOP_SUBJECTS: Final = (
    "mathematics",
    "physics",
    "chemistry",
    "biology",
    "english",
    "additional_mathematics",
    "computer_science",
    "business",
)
OTHER_SUBJECT_LABEL: Final = "Other"
MAX_OTHER_SUBJECTS: Final = 5
MAX_OTHER_SUBJECT_LENGTH: Final = 60

#: First day of the sitting window; a sitting is offered only while it is still ahead.
_SESSION_START_MONTH: Final = {"mj": 5, "on": 10}
_SESSION_LABEL: Final = {"mj": "May/June", "on": "Oct/Nov"}
_SESSION_RE: Final = re.compile(r"^(\d{4})-(mj|on)$")
SESSION_OPTION_COUNT: Final = 4

DEFAULT_REGION_PREFIX: Final = "+20"
_EGYPT_MOBILE_RE: Final = re.compile(r"^\+201[0125]\d{8}$")
_E164_RE: Final = re.compile(r"^\+[1-9]\d{7,14}$")

#: The consent wording lives here, versioned, so the server stores the canonical text for the
#: version a client names instead of trusting wording the client sends. Add a new version to
#: change the wording; never edit an old one (rows record which version each person saw).
CONSENT_VERSIONS: Final[dict[str, str]] = {
    "2026-11-v1": "Applying opts you in to Lemely emails.",
}
CURRENT_CONSENT_VERSION: Final = "2026-11-v1"

TOKEN_TTL_HOURS: Final = 24

#: How long an emailed confirmation link works, and the least time between two mails to one
#: address (a repeat sign-up for an unconfirmed address re-sends the link, at most this often).
CONFIRMATION_TTL: Final = timedelta(days=7)
CONFIRMATION_RESEND_INTERVAL: Final = timedelta(minutes=10)
#: Most confirmation mails one address gets in a window (the first plus three re-sends). A new
#: window opens once the latest link has expired, so a stranger re-submitting someone's address
#: can send them at most this many mails a week.
CONFIRMATION_MAX_MAILS: Final = 4
#: Where the emailed link points, as a frontend route the mail provider joins onto the app origin.
CONFIRMATION_LINK_PATH: Final = "/waitlist/confirm"

_CSV_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")
#: ``+`` then only digits and spaces (an exported phone) cannot form a formula, so it stays usable.
_PLAIN_PHONE_RE: Final = re.compile(r"^\+\d[\d ]{6,24}$")


MAX_NAME_LENGTH: Final = 100
#: ZWNJ and ZWJ are format characters but part of real Persian and Indic names: kept.
_JOINERS: Final = frozenset("\u200c\u200d")
_NAME_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean_name(raw: str) -> str:
    """Return the stored form of an applicant's name, or raise ``ValueError`` with the reason.

    Invisible format characters (Unicode category Cf: zero-width space, bidi controls, BOM) are
    removed first, except ZWNJ and ZWJ, which real names use. A name with nothing but format
    characters counts as empty. Surrounding whitespace is
    trimmed and runs of whitespace inside collapse to one space. Any
    Unicode letters are fine (Arabic, accented, CJK). Control characters (including tabs and
    line breaks) are refused rather than silently rewritten, and the length limit counts the
    trimmed result.
    """
    if _NAME_CONTROL_RE.search(raw):
        raise ValueError("Name cannot contain control characters.")
    stripped = "".join(ch for ch in raw if ch in _JOINERS or unicodedata.category(ch) != "Cf")
    name = " ".join(stripped.split())
    if not any(unicodedata.category(ch) != "Cf" for ch in name):
        raise ValueError("Enter your name.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Name must be {MAX_NAME_LENGTH} characters or fewer.")
    return name


def normalise_email(email: str) -> str:
    """Trim and lowercase: the uniqueness key."""
    return email.strip().lower()


def exam_session_options(today: date) -> list[tuple[str, str]]:
    """The next :data:`SESSION_OPTION_COUNT` sittings as ``(value, label)``, soonest first.

    ``today`` is a UTC date (the client computes the same in UTC). A sitting counts as upcoming
    while its first day is after ``today``: in November 2026 the
    first option is May/June 2027, not the Oct/Nov sitting already under way.
    """
    options: list[tuple[str, str]] = []
    year = today.year
    while len(options) < SESSION_OPTION_COUNT:
        for code in ("mj", "on"):
            if date(year, _SESSION_START_MONTH[code], 1) > today:
                options.append((f"{year}-{code}", f"{_SESSION_LABEL[code]} {year}"))
        year += 1
    return options[:SESSION_OPTION_COUNT]


def is_valid_exam_session(value: str, today: date) -> bool:
    """``True`` when ``value`` was offered by :func:`exam_session_options` around ``today``.

    ``today`` is the UTC date. The window of yesterday, today and tomorrow is accepted, so a
    browser in another timezone (whose "today" differs by up to a day) is never refused an
    option it was legitimately shown.
    """
    if _SESSION_RE.match(value) is None:
        return False
    return any(
        value in {v for v, _ in exam_session_options(today + timedelta(days=offset))}
        for offset in (-1, 0, 1)
    )


def normalise_phone(raw: str) -> str | None:
    """Return the E.164 form of ``raw``, or ``None`` when it is not a plausible number.

    A number with no ``+``/``00`` prefix is read as Egyptian (the product's home market): a
    leading national ``0`` is dropped and ``+20`` prefixed. Egyptian numbers must be mobiles
    (``+20 1[0125]xxxxxxxx``); any other country only has to be well-formed E.164.
    """
    cleaned = re.sub(r"[\s().\-]", "", raw)
    if not cleaned or not re.fullmatch(r"\+?\d+", cleaned):
        return None
    if cleaned.startswith("+"):
        number = cleaned
    elif cleaned.startswith("00"):
        number = "+" + cleaned[2:]
    elif cleaned.startswith("0"):
        number = DEFAULT_REGION_PREFIX + cleaned[1:]
    else:
        number = DEFAULT_REGION_PREFIX + cleaned
    if number.startswith("+20"):
        return number if _EGYPT_MOBILE_RE.match(number) else None
    return number if _E164_RE.match(number) else None


def csv_safe(value: object) -> str:
    """Render one CSV cell, neutralising spreadsheet formula injection.

    A cell that starts with ``= + - @``, a tab or a CR is read as a formula by Excel and
    Sheets, so it is prefixed with an apostrophe (it then shows as plain text). The one
    exemption is ``+`` followed only by digits and spaces (an exported phone), which cannot be a
    formula.
    """
    text = "" if value is None else str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES) and not _PLAIN_PHONE_RE.match(text):
        return "'" + text
    return text


def phone_for_export(e164: str | None) -> str | None:
    """Group a stored E.164 number with spaces (``+20 100 123 4567``).

    A bare ``+201001234567`` is read by Excel and Sheets as a number and shown as
    ``2.01E+11``; with spaces it stays text, and still reads as a phone number.
    """
    if e164 is None or not _E164_RE.match(e164):
        return e164
    digits = e164[1:]
    code_len = 1 if digits[0] in "17" else 2
    code, rest = digits[:code_len], digits[code_len:]
    groups = [rest[: len(rest) - 7 if len(rest) > 7 else 3]]
    tail = rest[len(groups[0]) :]
    groups += [tail[:3], tail[3:]] if tail else []
    return "+" + " ".join([code, *[g for g in groups if g]])


def new_completion_token() -> tuple[str, str]:
    """A fresh ``(token, sha256 hex digest)``; only the digest is ever stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    """The stored form of a completion token."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_confirmation_token() -> tuple[str, str]:
    """A fresh ``(token, sha256 hex digest)`` for the email confirmation link."""
    return new_completion_token()


def confirmation_link(token: str) -> str:
    """The frontend route the confirmation mail links to (the provider makes it absolute)."""
    return f"{CONFIRMATION_LINK_PATH}?token={token}"
