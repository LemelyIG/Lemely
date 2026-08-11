"""D5.1 §0 / D5.6 §5 pin: the friends DTOs cannot carry a mark (P5.4 chunk B).

Introspects the Pydantic models' declared field sets directly, rather than
eyeballing the source, mirroring ``tests/test_schemas_leaderboard.py``'s
"a comment saying 'don't put a mark here' is not a control; a failing test
is" reasoning.
"""

from __future__ import annotations

from lemely.web.schemas_friends import (
    FriendDTO,
    FriendRequestCreateDTO,
    FriendRequestDTO,
    FriendsPageDTO,
)

# Substrings that would signal a mark/grade leaked onto this public surface
# (D5.1 §0 / UI spec §1.4). Matched case-insensitively against every field name.
_FORBIDDEN_SUBSTRINGS = ("mark", "percent", "grade", "accuracy", "score", "confidence")

_EXPECTED_FRIEND_FIELDS = {
    "friendshipId",
    "userId",
    "displayName",
    "xp",
    "streak",
    "optedOut",
    "friendsSince",
}
_EXPECTED_REQUEST_FIELDS = {"friendshipId", "userId", "displayName", "requestedAt", "status"}
_EXPECTED_PAGE_FIELDS = {"friendCode", "friends", "incoming", "outgoing"}
_EXPECTED_CREATE_FIELDS = {"friendCode"}


class TestNoMarkShapedFields:
    def test_friend_dto_field_set_is_exactly_identity_xp_streak_and_opt_out(self) -> None:
        assert set(FriendDTO.model_fields) == _EXPECTED_FRIEND_FIELDS

    def test_friend_request_dto_field_set_has_no_xp_or_streak(self) -> None:
        assert set(FriendRequestDTO.model_fields) == _EXPECTED_REQUEST_FIELDS

    def test_friends_page_dto_field_set(self) -> None:
        assert set(FriendsPageDTO.model_fields) == _EXPECTED_PAGE_FIELDS

    def test_friend_request_create_dto_field_set(self) -> None:
        assert set(FriendRequestCreateDTO.model_fields) == _EXPECTED_CREATE_FIELDS

    def test_friend_dto_has_no_field_matching_a_forbidden_substring(self) -> None:
        lowered = {name.lower() for name in FriendDTO.model_fields}
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"FriendDTO has a field matching forbidden substring {forbidden!r}: {matches}"
            )

    def test_friend_request_dto_has_no_field_matching_a_forbidden_substring(self) -> None:
        lowered = {name.lower() for name in FriendRequestDTO.model_fields}
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"FriendRequestDTO has a field matching forbidden substring "
                f"{forbidden!r}: {matches}"
            )


class TestOptedOutNumbersAreNullable:
    def test_xp_field_type_admits_none(self) -> None:
        annotation = FriendDTO.model_fields["xp"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_streak_field_type_admits_none(self) -> None:
        annotation = FriendDTO.model_fields["streak"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_none_xp_and_streak_construct_without_error(self) -> None:
        friend = FriendDTO(
            friendshipId="f1",
            userId="u1",
            displayName="Ada",
            xp=None,
            streak=None,
            optedOut=True,
            friendsSince=None,
        )
        assert friend.xp is None
        assert friend.streak is None


class TestFriendRequestStatusIsLiteral:
    def test_status_accepts_pending_and_accepted(self) -> None:
        for value in ("pending", "accepted"):
            req = FriendRequestDTO(
                friendshipId="f1",
                userId="u1",
                displayName="Ada",
                requestedAt="2026-08-05T12:00:00Z",
                status=value,
            )
            assert req.status == value
