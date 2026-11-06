"""Contact-detail detection and the meeting-link allowlist (SPEC SC-7, section e.1).

Two jobs, one module: keep phone numbers, emails and off-platform handles out of
free text a student or parent can read, and let a tutor attach a meeting link
only if it points at one of five known meeting hosts. Both are tested from the
attacker's side: separators, digit scripts and look-alike hosts.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from lemely.core.contact_patterns import (
    MEETING_HOSTS,
    ContactMatch,
    find_contact_details,
    meeting_link_allowed,
)

_SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"

# Arabic-Indic digits U+0660..U+0669, built from code points so the source stays ASCII.
_ARABIC_INDIC = "".join(chr(0x660 + d) for d in range(10))
_EXTENDED_ARABIC_INDIC = "".join(chr(0x6F0 + d) for d in range(10))


def _to_arabic_indic(digits: str) -> str:
    return "".join(_ARABIC_INDIC[int(c)] if c.isdigit() else c for c in digits)


def _to_extended(digits: str) -> str:
    return "".join(_EXTENDED_ARABIC_INDIC[int(c)] if c.isdigit() else c for c in digits)


def _kinds(text: str) -> list[str]:
    return [m.kind for m in find_contact_details(text)]


_LATIN_MOBILES = [
    "01012345678",
    "01112345678",
    "01212345678",
    "01512345678",
    "010 1234 5678",
    "010-1234-5678",
    "010.1234.5678",
    "0101 234 5678",
    "(010) 1234-5678",
    "+201012345678",
    "+20 10 1234 5678",
    "+20 010 1234 5678",
    "+20-10-1234-5678",
    "00201012345678",
    "0020 10 1234 5678",
    "0 1 0 1 2 3 4 5 6 7 8",
    "010\U0000200b1234\U0000200b5678",
]


@pytest.mark.parametrize("number", _LATIN_MOBILES)
def test_contact_patterns_egyptian_mobile_latin_and_arabic_indic_digits(number: str) -> None:
    for variant in (number, _to_arabic_indic(number), _to_extended(number)):
        text = f"call me on {variant} after school"
        matches = find_contact_details(text)
        assert [m.kind for m in matches] == ["phone"], variant
        found = matches[0]
        assert text[found.start : found.end] == found.text
        # The match covers every digit of the number, whatever script it was typed in.
        assert sum(c.isdigit() for c in found.text) == sum(c.isdigit() for c in variant)


def test_contact_patterns_phone_normalises_fullwidth_digits() -> None:
    fullwidth = "".join(chr(0xFF10 + int(c)) if c.isdigit() else c for c in "01012345678")
    assert _kinds(f"ring {fullwidth}") == ["phone"]


@pytest.mark.parametrize(
    ("script", "zero"),
    [
        ("mathematical bold", 0x1D7CE),
        ("mathematical double-struck", 0x1D7D8),
        ("mathematical monospace", 0x1D7F6),
        ("devanagari", 0x0966),
        ("bengali", 0x09E6),
        ("thai", 0x0E50),
        ("nko", 0x07C0),
    ],
)
def test_contact_patterns_any_unicode_decimal_digit_script_is_a_digit(
    script: str, zero: int
) -> None:
    digits = "".join(chr(zero + int(c)) for c in "01012345678")
    text = f"ring {digits} now"
    matches = find_contact_details(text)
    assert [m.kind for m in matches] == ["phone"], script
    # Offsets index the caller's text even where a digit is outside the BMP.
    assert text[matches[0].start : matches[0].end] == digits


def test_contact_patterns_superscript_digits_are_not_decimal_digits() -> None:
    # Superscripts are numeric but not decimal; "x\u00b2" style maths must stay clean.
    assert find_contact_details("area is 12\u00b2 and 34\u00b3") == []


@pytest.mark.parametrize(
    "text",
    ["online.Site", "us.Us", "@home", "5@home", "0 1 0 1 2 3 4 5 6 7 8"],
)
def test_contact_patterns_known_deliberate_false_positives_stay_flagged(text: str) -> None:
    # Recorded in the module docstring: the detector prefers refusing these to missing a
    # real number or address. This pins the choice so a loosening is a decision, not drift.
    assert find_contact_details(text) != []


def test_contact_patterns_mixed_scripts_in_one_number() -> None:
    mixed = "010" + _to_arabic_indic("12345") + "678"
    assert _kinds(mixed) == ["phone"]


@pytest.mark.parametrize(
    "number",
    ["+966 50 123 4567", "+44 7700 900123", "+1 202 555 0143", "+971501234567"],
)
def test_contact_patterns_international_number_with_plus_prefix(number: str) -> None:
    assert _kinds(f"my number is {number}") == ["phone"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mail sara.m@example.com please", "email"),
        ("Sara_M+tutor@Mail.Example.co.uk", "email"),
        ("sara@gmail.com", "email"),
        ("sara@gmail", "email"),
        ("https://example.com/sara", "url"),
        ("http://sara.example.org", "url"),
        ("HTTPS://EXAMPLE.COM", "url"),
        ("www.sara-tutoring.com", "url"),
        ("visit sara-tutoring.com for details", "url"),
        ("see sara.tutoring.net/profile", "url"),
        ("tutor.io", "url"),
        ("follow @sara_tutor for tips", "handle"),
        ("@sara.m", "handle"),
        ("add me on whatsapp", "platform"),
        ("WhatsApp me", "platform"),
        ("my telegram is open", "platform"),
        ("find me on Instagram", "platform"),
        ("facebook group", "platform"),
        ("snapchat", "platform"),
        ("TikTok", "platform"),
        ("wa.me/201012345678", "platform"),
        ("t.me/sara_tutor", "platform"),
        (
            "message me on " + "\U00000648\U00000627\U0000062a\U00000633\U00000627\U00000628",
            "platform",
        ),
        ("\U0000062a\U00000644\U0000064a\U0000062c\U00000631\U00000627\U00000645", "platform"),
        (
            "\U00000627\U00000646\U00000633\U0000062a\U0000062c\U00000631\U00000627\U00000645",
            "platform",
        ),
    ],
)
def test_contact_patterns_email_url_social_handles(text: str, kind: str) -> None:
    matches = find_contact_details(text)
    assert matches, text
    assert kind in {m.kind for m in matches}, (text, matches)


def test_contact_patterns_email_is_one_match_not_email_plus_handle() -> None:
    matches = find_contact_details("write to sara.m@example.com today")
    assert [m.kind for m in matches] == ["email"]
    assert matches[0].text == "sara.m@example.com"


def test_contact_patterns_url_with_scheme_is_one_match() -> None:
    matches = find_contact_details("go to https://example.com/a?b=1 now")
    assert [m.kind for m in matches] == ["url"]
    assert matches[0].text.startswith("https://example.com/a")


def test_contact_patterns_matches_are_ordered_and_do_not_overlap() -> None:
    text = "email a@b.com or 01012345678 or @handle or example.com"
    matches = find_contact_details(text)
    assert [m.kind for m in matches] == ["email", "phone", "handle", "url"]
    spans = [(m.start, m.end) for m in matches]
    assert spans == sorted(spans)
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert end <= start


def test_contact_patterns_match_is_a_frozen_dataclass() -> None:
    match = find_contact_details("01012345678")[0]
    assert isinstance(match, ContactMatch)
    with pytest.raises(AttributeError):
        match.kind = "email"


@pytest.mark.parametrize(
    "text",
    [
        "A*",
        "72/80",
        "17:00",
        "0625/42",
        "I got A* in IGCSE Maths 0580/42 in May/June 2024, 72/80 on paper 4 at 17:00.",
        "Tuesday 17:00-18:30 or Thursday 09:00",
        "Grades 9-1, Paper 4.1 and 2.5 hours",
        "2026-10-29 at 14:00Z",
        "Aim for 8, 9 or A*, then 7 8 9 in the mocks",
        "Cambridge IGCSE 0610/32 and 0620/22 and 0625/42",
        "Marks: 12 15 18 20 22 25 27 30 32 35",
        "e.g. use i.e. the same method etc.",
        "Hello.Thanks for the lesson",
        "Version 3.14 of the booklet",
        "I scored 100% and 98.5% in two mocks",
        "ages 11-16, 45 to 90 minutes, 5 days a week",
        "Based in Maadi, Cairo",
        "",
        "   ",
    ],
)
def test_contact_patterns_no_false_positive_on_grades_and_times(text: str) -> None:
    assert find_contact_details(text) == []


def test_contact_patterns_ten_digit_runs_and_other_prefixes_are_not_egyptian_mobiles() -> None:
    assert find_contact_details("0101234567") == []  # one digit short
    assert find_contact_details("01312345678") == []  # 013 is not a mobile prefix
    assert find_contact_details("0610123456789") == []  # a paper-code-like long number


def test_contact_patterns_phone_not_matched_inside_a_longer_digit_run() -> None:
    assert find_contact_details("9901012345678") == []
    assert find_contact_details("010123456789") == []  # twelve digits


def test_contact_patterns_separator_run_is_bounded() -> None:
    text = "0" + " " * 5000 + "1" + " " * 5000 + "0"
    assert find_contact_details(text) == []


def test_meeting_hosts_constant_equals_spec_text() -> None:
    spec = _SPEC.read_text(encoding="utf-8")
    block = re.search(r"^MEETING_HOSTS: Final = \((?P<hosts>[^)]*)\)", spec, re.MULTILINE)
    assert block is not None
    expected = tuple(re.findall(r'"([^"]+)"', block.group("hosts")))
    assert len(expected) == 5
    assert expected == MEETING_HOSTS


@pytest.mark.parametrize(
    "url",
    [
        "https://meet.google.com/abc-defg-hij",
        "https://zoom.us/j/1234567890?pwd=abc",
        "https://us02web.zoom.us/j/1234567890",
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting",
        "https://teams.live.com/meet/9876543210",
        "https://whereby.com/sara-room",
        "https://sub.whereby.com/sara-room",
        "https://meet.google.com:443/abc-defg-hij",
        "HTTPS://Meet.Google.Com/abc-defg-hij",
        "https://zoom.us/j/1?next=https://evil.example.com@x",
    ],
)
def test_meeting_link_allowlist_accepts_known_hosts(url: str) -> None:
    assert meeting_link_allowed(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://meet.google.com/abc-defg-hij",
        "http://zoom.us/j/1",
        "https://user@zoom.us/j/1",
        "https://user:secret@zoom.us/j/1",
        "https://zoom.us@evil.example.com/j/1",
        "https://zoom.us:pw@evil.example.com/",
        "https://wa.me/201012345678",
        "https://t.me/sara",
        "https://chat.whatsapp.com/abc",
        "https://example.com/zoom.us",
        "ftp://zoom.us/j/1",
        "javascript:alert(1)",
        "zoom.us/j/1",
        "//zoom.us/j/1",
        "https:///zoom.us/j/1",
        "https://",
        "",
        "   ",
    ],
)
def test_meeting_link_allowlist_rejects_userinfo_http_wa_me(url: str) -> None:
    assert meeting_link_allowed(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://zoom.us.evil.example.com/j/1",
        "https://evilzoom.us/j/1",
        "https://notzoom.us/j/1",
        "https://zoom.us.evil/j/1",
        "https://xmeet.google.com/abc",
        "https://meet.google.com.evil.example.com/abc",
        "https://whereby.com.evil.example.com/room",
        "https://zoom.us./j/1",
        "https://evil.example.com\\.zoom.us/j/1",
        "https://zoom.us\\.evil.example.com/j/1",
        "https://zoom.us:8443/j/1",
        "https://zoom.us:80/j/1",
        "https://zoom.us:0/j/1",
        "https://zoom.us:99999/j/1",
        "https://zoom.us:abc/j/1",
        "https://-.zoom.us/j/1",
        "https://-zoom.us/j/1",
        "https://a.-b.zoom.us/j/1",
        "https://zoom.us:/j/1",
        "https://127.0.0.1/zoom.us",
        "https://[::1]/",
        "https://zoom.us /j/1",
        "https://zoom.us/j/1\n",
        "https://zoom.us/j/\t1",
        "https://\U00000437oom.us/j/1",  # Cyrillic z
        "https://zoom.us/j/\U0000202e1",  # bidi override in the path
        "https://zoom.us/j/" + "a" * 500,  # longer than the 500-character column
    ],
)
def test_meeting_link_rejects_lookalike_host_and_port(url: str) -> None:
    assert meeting_link_allowed(url) is False
