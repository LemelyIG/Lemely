"""D5.1 §0 pin: the student announcement DTOs cannot carry a mark (P5.5 chunk B).

Introspects the Pydantic models' declared field sets directly, rather than
eyeballing the source, mirroring ``tests/test_schemas_friends.py`` and
``tests/test_schemas_leaderboard.py``'s "a comment saying 'don't put a mark
here' is not a control; a failing test is" reasoning.

Two more properties are pinned here because both are load-bearing and both
look like tidy-ups to a future reader:

* the reader surface is **read-only** — no create/update body model exists in
  this module, so a student can never compose an announcement through it;
* ``readAt`` is a nullable timestamp and there is no ``isRead`` boolean beside
  it. Unread is the absence of a receipt (migration ``0016``); a second field
  restating the same fact is a field that can drift out of step with it.
"""

from __future__ import annotations

import lemely.web.schemas_announcements_student as module
from lemely.web.schemas import ApiModel
from lemely.web.schemas_announcements_student import (
    AnnouncementReadReceiptDTO,
    StudentAnnouncementDTO,
    StudentAnnouncementsPageDTO,
    UnreadAnnouncementCountDTO,
)

# Substrings that would signal a mark/grade leaked onto this public surface
# (D5.1 §0 / UI spec §1.4). Matched case-insensitively against every field name.
_FORBIDDEN_SUBSTRINGS = ("mark", "percent", "grade", "accuracy", "score", "confidence")

_EXPECTED_ANNOUNCEMENT_FIELDS = {
    "announcementId",
    "scope",
    "classId",
    "schoolId",
    "title",
    "body",
    "publishedAt",
    "readAt",
    "authorId",
}


class TestNoMarkShapedFields:
    def test_student_announcement_dto_field_set_is_exactly_the_reader_contract(self) -> None:
        assert set(StudentAnnouncementDTO.model_fields) == _EXPECTED_ANNOUNCEMENT_FIELDS

    def test_page_dto_field_set(self) -> None:
        assert set(StudentAnnouncementsPageDTO.model_fields) == {"announcements"}

    def test_unread_count_dto_field_set(self) -> None:
        assert set(UnreadAnnouncementCountDTO.model_fields) == {"unreadCount"}

    def test_receipt_dto_field_set(self) -> None:
        assert set(AnnouncementReadReceiptDTO.model_fields) == {"announcementId", "readAt"}

    def test_no_dto_has_a_field_matching_a_forbidden_substring(self) -> None:
        for model in (
            StudentAnnouncementDTO,
            StudentAnnouncementsPageDTO,
            UnreadAnnouncementCountDTO,
            AnnouncementReadReceiptDTO,
        ):
            lowered = {name.lower() for name in model.model_fields}
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                matches = [name for name in lowered if forbidden in name]
                assert not matches, (
                    f"{model.__name__} has a field matching forbidden substring "
                    f"{forbidden!r}: {matches}"
                )


class TestTheReaderSurfaceIsReadOnly:
    def test_the_module_declares_exactly_these_four_models(self) -> None:
        """No write body may appear here.

        The teacher composer's body lives in ``schemas_announcements``; a
        create/update model appearing in *this* module would mean the student
        surface had quietly grown a way to publish.
        """
        declared = {
            name
            for name, obj in vars(module).items()
            if isinstance(obj, type) and issubclass(obj, ApiModel) and obj is not ApiModel
        }
        assert declared == set(_all_exported())

    def test_exports_match_the_declared_models(self) -> None:
        assert set(module.__all__) == set(_all_exported())


class TestUnreadIsAnAbsenceNotAFlag:
    def test_read_at_admits_none(self) -> None:
        annotation = StudentAnnouncementDTO.model_fields["readAt"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_there_is_no_boolean_read_flag_beside_the_timestamp(self) -> None:
        lowered = {name.lower() for name in StudentAnnouncementDTO.model_fields}
        assert "isread" not in lowered
        assert "read" not in lowered
        assert "unread" not in lowered


def _all_exported() -> set[str]:
    return {
        "AnnouncementReadReceiptDTO",
        "StudentAnnouncementDTO",
        "StudentAnnouncementsPageDTO",
        "UnreadAnnouncementCountDTO",
    }
