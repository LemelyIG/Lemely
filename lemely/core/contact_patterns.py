"""Contact-detail detection and the meeting-link allowlist (SPEC SC-7).

Lemely lets a tutor write a headline, a bio, a booking reason and a note to a
student who may be a minor. Contact details in those fields would move the
relationship off the platform, past the audit log and the moderation queue, so
every user-written tutoring field passes :func:`find_contact_details` and is
refused when it returns anything. The same module owns the one place a URL is
*allowed*: the meeting link a tutor attaches to an accepted virtual booking,
which must point at one of :data:`MEETING_HOSTS` (:func:`meeting_link_allowed`).

The detector is a deliberate trade: it prefers refusing a borderline sentence
(the author edits and resubmits) to letting a phone number through. What it must
*not* do is refuse ordinary tutoring prose, so the patterns are anchored on
shapes that grades, marks, times and paper codes never take ("A*", "72/80",
"17:00", "0625/42" are tested negatives).

Evasions it handles: digits of any script (every Unicode decimal digit is
mapped one-for-one to ASCII before matching, so match offsets still index the
caller's original text), runs of up to three separator characters between
digits (spaces, dots, dashes, underscores, brackets, zero-width characters), the
``+20`` / ``0020`` country prefixes with or without the trunk ``0``.

Known evasions it does not catch, left to the moderators: spelled-out numbers
("zero one zero ..."), a slash, comma or Arabic comma (U+060C) between digits,
four or more separator characters between two digits, fullwidth or styled
*letters* in a domain or messenger name, and addresses split across words.

Known false positives, kept on purpose because refusing is cheaper than missing:
a word pair that reads as a domain on a listed TLD ("online.Site", "us.Us"), a
bare ``@word`` or ``digit@word`` ("@home", "5@home") which reads as a handle or a
dotless email, and any list of eleven or so single digits starting 01x written
with spaces ("0 1 0 1 2 3 ..."). The TLD list is not widened to chase more.

Pure: no I/O, no framework.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlsplit

ContactKind = Literal["phone", "email", "url", "handle", "platform"]

MEETING_HOSTS: Final = (
    "meet.google.com",
    "zoom.us",
    "teams.microsoft.com",
    "teams.live.com",
    "whereby.com",
)

# A DNS host: two or more dot-separated labels, each starting with a letter or digit.
_HOST: Final = r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+"

# ``meeting_link`` is varchar(500) (SPEC section a.2).
_MAX_LINK_LENGTH: Final = 500


@dataclass(frozen=True, slots=True)
class ContactMatch:
    """One detected contact detail: its kind and where it sits in the checked text."""

    kind: ContactKind
    start: int
    end: int
    text: str


# Whitespace, dot, dash, underscore, brackets, and the zero-width / bidi marks people
# slip between digits so the number no longer looks like one.
_SEP: Final = r"[\s.\-_()\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060\U0000feff]{0,3}"

# Egyptian mobile: trunk ``0`` + ``1[0125]`` + 8 digits, or the country prefix
# (``+20`` / ``0020``, trunk zero optional) + ``1[0125]`` + 8 digits. The prefix form
# is listed first: ``0020...`` must not be read as a bare ``0`` start.
_EGYPT_MOBILE: Final = (
    rf"(?<!\d)(?:(?:\+|00){_SEP}20{_SEP}0?|0){_SEP}1{_SEP}[0125](?:{_SEP}\d){{8}}(?!\d)"
)
# Any other international number: an explicit ``+``, then 9 to 15 digits.
_INTERNATIONAL: Final = rf"(?<![\d+])\+{_SEP}\d(?:{_SEP}\d){{8,14}}(?!\d)"

# A dotted domain, or a dotless one of two or more characters ("sara@gmail").
_EMAIL: Final = r"(?<![\w.+-])[\w.+-]+@(?:[\w-]+(?:\.[\w-]+)+|[\w-]{2,})"

_TLDS: Final = (
    "com|net|org|edu|info|biz|io|co|eg|uk|us|ai|app|dev|xyz|ly|gl|gg|tv|link|online|site|page"
)
_URL_WITH_SCHEME: Final = r"\b(?:https?|ftp)://[^\s<>\"']+"
_URL_WWW: Final = r"(?<![\w.@/-])www\.[^\s<>\"']+"
# A bare domain: dotted labels ending in a well-known TLD, not the tail of a longer word.
_BARE_DOMAIN: Final = (
    r"(?<![\w@.-])(?:[a-z0-9-]+\.)+"
    rf"(?:{_TLDS})\b(?![\w@-])"
    r"(?:/[^\s<>\"']*)?"
)

_HANDLE: Final = r"(?<![\w@.])@[\w][\w.]{1,29}"

# Short links that name a messenger outright, then messenger names in Latin and Arabic.
_PLATFORM_LINK: Final = r"(?<![\w.])(?:wa|t)\.me\b(?:/[^\s<>\"']*)?"
_ARABIC_PLATFORM_WORDS: Final = (
    # whatsapp
    "\U00000648\U00000627\U0000062a\U00000633\U00000627\U00000628",
    # whats app
    "\U00000648\U00000627\U0000062a\U00000633 \U00000627\U00000628",
    # telegram
    "\U0000062a\U00000644\U0000064a\U0000062c\U00000631\U00000627\U00000645",
    # telegram, other spelling
    "\U0000062a\U00000644\U0000063a\U00000631\U00000627\U00000645",
    # instagram
    "\U00000627\U00000646\U00000633\U0000062a\U0000062c\U00000631\U00000627\U00000645",
    # instagram, other spelling
    "\U00000627\U00000646\U00000633\U0000062a\U0000063a\U00000631\U00000627\U00000645",
    # facebook
    "\U00000641\U0000064a\U00000633\U00000628\U00000648\U00000643",
    # snapchat
    "\U00000633\U00000646\U00000627\U00000628 \U00000634\U00000627\U0000062a",
    # tiktok
    "\U0000062a\U0000064a\U00000643 \U0000062a\U00000648\U00000643",
)
_PLATFORM_WORDS: Final = (
    r"(?<!\w)(?:whats\s?app|telegram|instagram|insta|facebook|snapchat|tiktok)(?!\w)|"
    + "|".join(re.escape(word) for word in _ARABIC_PLATFORM_WORDS)
)

# Priority order = specificity order. An email contains a handle-shaped tail and a
# domain; a URL contains a bare domain; so the more specific kind claims the span first.
_PATTERNS: Final[tuple[tuple[ContactKind, re.Pattern[str]], ...]] = (
    ("email", re.compile(_EMAIL, re.IGNORECASE)),
    ("url", re.compile(_URL_WITH_SCHEME, re.IGNORECASE)),
    ("url", re.compile(_URL_WWW, re.IGNORECASE)),
    ("platform", re.compile(_PLATFORM_LINK, re.IGNORECASE)),
    ("phone", re.compile(_EGYPT_MOBILE)),
    ("phone", re.compile(_INTERNATIONAL)),
    ("url", re.compile(_BARE_DOMAIN, re.IGNORECASE)),
    ("handle", re.compile(_HANDLE)),
    ("platform", re.compile(_PLATFORM_WORDS, re.IGNORECASE)),
)

# Characters that end a sentence rather than a link or handle.
_TRAILING_PUNCTUATION: Final = ".,;:!?)]}"


def find_contact_details(text: str) -> list[ContactMatch]:
    """Return every contact detail in ``text``, ordered by position, never overlapping.

    An empty list means the text is clean. Offsets index the *original* ``text``.
    """
    normalised = _ascii_digits(text)
    taken: list[tuple[int, int]] = []
    found: list[ContactMatch] = []
    for kind, pattern in _PATTERNS:
        for hit in pattern.finditer(normalised):
            start, end = hit.span()
            if kind in ("url", "handle", "platform"):
                end = _trim_trailing_punctuation(normalised, start, end)
            if end <= start or any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            taken.append((start, end))
            found.append(ContactMatch(kind=kind, start=start, end=end, text=text[start:end]))
    found.sort(key=lambda match: match.start)
    return found


def _ascii_digits(text: str) -> str:
    """Map every Unicode decimal digit (any script) to its ASCII digit, code point for code point.

    ``unicodedata.decimal`` is defined for exactly the characters that read as a
    digit 0-9 in some script (Arabic-Indic, Devanagari, mathematical bold, ...),
    and each is a single code point, so offsets into the result are offsets into
    ``text``. Superscripts and fractions are numeric but not decimal, and stay put.
    """
    return "".join(
        str(value) if (value := unicodedata.decimal(char, None)) is not None else char
        for char in text
    )


def _trim_trailing_punctuation(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in _TRAILING_PUNCTUATION:
        end -= 1
    return end


def meeting_link_allowed(url: str) -> bool:
    """True only for an ``https`` link to a meeting host, with nothing that could redirect.

    Accepted: scheme ``https``, no userinfo, no port or the default port ``443``,
    and a host that equals one of :data:`MEETING_HOSTS` or is a subdomain of one
    (``us02web.zoom.us``). Everything else is refused, notably:

    * ``zoom.us.evil.example`` and ``evilzoom.us``: the host must *end with*
      ``.`` plus an allowed host, not merely contain it;
    * ``https://zoom.us@evil.example``: userinfo is the classic spoof;
    * a backslash, any whitespace or control character, or any non-ASCII character
      anywhere in the string: browsers treat a backslash like a slash and normalise
      look-alike letters, so the host a check sees can differ from the host a
      browser visits;
    * a trailing-dot FQDN, an IP literal, anything longer than the column.
    """
    if not url or len(url) > _MAX_LINK_LENGTH or not _is_plain_ascii(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.netloc:
        return False
    host, has_port, port = parts.netloc.partition(":")
    if "@" in parts.netloc or (has_port and port != "443"):
        return False
    if re.fullmatch(_HOST, host.lower()) is None:
        return False
    host = host.lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in MEETING_HOSTS)


def _is_plain_ascii(value: str) -> bool:
    return value.isascii() and value.isprintable() and "\\" not in value and " " not in value
