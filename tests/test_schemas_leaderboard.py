"""D5.1 §0 pin: the leaderboard row/viewer DTOs cannot carry a mark (P5.3 chunk B).

Introspects the Pydantic models' declared field sets directly, rather than
eyeballing the source, per the brief this chunk was built against: "a comment
saying 'don't put a mark here' is not a control; a failing test is."
"""

from __future__ import annotations

from lemely.web.schemas_leaderboard import LeaderboardRowDTO, LeaderboardViewerDTO

# Substrings that would signal a mark/grade leaked onto this public surface
# (D5.1 §0 / UI spec §1.4). Matched case-insensitively against every field name.
_FORBIDDEN_SUBSTRINGS = ("mark", "percent", "grade", "accuracy", "score", "confidence")

_EXPECTED_ROW_FIELDS = {"userId", "displayName", "xp", "rank"}
_EXPECTED_VIEWER_FIELDS = {"userId", "displayName", "xp", "rank"}


class TestNoMarkShapedFields:
    def test_row_dto_field_set_is_exactly_display_identity_xp_and_rank(self) -> None:
        assert set(LeaderboardRowDTO.model_fields) == _EXPECTED_ROW_FIELDS

    def test_viewer_dto_field_set_is_exactly_display_identity_xp_and_rank(self) -> None:
        assert set(LeaderboardViewerDTO.model_fields) == _EXPECTED_VIEWER_FIELDS

    def test_row_dto_has_no_field_matching_a_forbidden_substring(self) -> None:
        lowered = {name.lower() for name in LeaderboardRowDTO.model_fields}
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"LeaderboardRowDTO has a field matching forbidden substring "
                f"{forbidden!r}: {matches}"
            )

    def test_viewer_dto_has_no_field_matching_a_forbidden_substring(self) -> None:
        lowered = {name.lower() for name in LeaderboardViewerDTO.model_fields}
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"LeaderboardViewerDTO has a field matching forbidden substring "
                f"{forbidden!r}: {matches}"
            )


class TestViewerRankIsNullable:
    def test_rank_field_type_admits_none(self) -> None:
        annotation = LeaderboardViewerDTO.model_fields["rank"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_none_rank_constructs_without_error(self) -> None:
        viewer = LeaderboardViewerDTO(userId="u1", displayName="Ada", xp=0, rank=None)
        assert viewer.rank is None

    def test_row_dto_rank_is_not_nullable(self) -> None:
        """Inverse: unlike the viewer, a ranked row's rank is always real (never None)."""
        annotation = LeaderboardRowDTO.model_fields["rank"].annotation
        assert type(None) not in getattr(annotation, "__args__", (annotation,))
