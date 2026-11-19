"""``web/src/lib/waitlist-api.ts`` must carry the server's vocabularies verbatim.

The client exports the lists the UI renders; if one drifts from ``lemely.core.waitlist`` the
form would offer a value the server then refuses (or hide one it accepts).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lemely.core.waitlist import ALL_SUBJECTS, EXAM_BOARDS, LEVELS, ROLES, STATUSES, TOP_SUBJECTS

SOURCE = (Path(__file__).resolve().parents[1] / "web/src/lib/waitlist-api.ts").read_text(
    encoding="utf-8"
)


def _tuple(name: str) -> tuple[str, ...]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const", SOURCE, re.S)
    assert match, name
    return tuple(re.findall(r"'([^']+)'", match.group(1)))


@pytest.mark.parametrize(
    ("name", "server"),
    [
        ("WAITLIST_ROLES", ROLES),
        ("WAITLIST_LEVELS", LEVELS),
        ("WAITLIST_BOARDS", EXAM_BOARDS),
        ("WAITLIST_STATUSES", STATUSES),
    ],
)
def test_enum_vocabularies_match(name: str, server: tuple[str, ...]) -> None:
    assert _tuple(name) == server


def test_subjects_match_values_labels_and_order() -> None:
    match = re.search(r"export const ALL_SUBJECTS = \[(.*?)\] as const", SOURCE, re.S)
    assert match
    pairs = re.findall(r"value: '([^']+)', label: '([^']+)'", match.group(1))
    assert dict(pairs) == ALL_SUBJECTS
    assert [value for value, _ in pairs] == list(ALL_SUBJECTS)


def test_top_subjects_match_in_order() -> None:
    assert _tuple("TOP_SUBJECT_VALUES") == TOP_SUBJECTS


def _const(name: str) -> str:
    match = re.search(rf"export const {name} =\s*'([^']*)'", SOURCE)
    assert match, name
    return match.group(1)


def test_consent_version_and_text_match_the_server() -> None:
    from lemely.core.waitlist import CONSENT_VERSIONS, CURRENT_CONSENT_VERSION

    assert _const("WAITLIST_CONSENT_VERSION") == CURRENT_CONSENT_VERSION
    assert _const("WAITLIST_CONSENT_TEXT") == CONSENT_VERSIONS[CURRENT_CONSENT_VERSION]


def test_phone_message_matches_the_server() -> None:
    from lemely.web.schemas_waitlist import PHONE_MESSAGE

    assert _const("WAITLIST_PHONE_MESSAGE") == PHONE_MESSAGE
