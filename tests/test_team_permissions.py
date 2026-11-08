"""Assistant role presets and per-permission toggles (spec §2.3, §7)."""

from __future__ import annotations

import pytest

from lemely.core.team_permissions import (
    PRESET_PERMISSIONS,
    AssistantRole,
    TeamPermission,
    UnknownPermissionError,
    effective_permissions,
    validate_overrides,
)


def test_permission_values_match_the_index_contract() -> None:
    assert {p.value for p in TeamPermission} == {
        "mark",
        "regrade",
        "generate_quiz",
        "manage_classes",
        "view_results",
        "manage_students",
        "view_usage",
    }


def test_billing_and_seats_are_never_permissions() -> None:
    for permission in TeamPermission:
        for forbidden in ("billing", "seat", "plan", "assistant", "cap"):
            assert forbidden not in permission.value


def test_co_teacher_has_everything() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.CO_TEACHER] == frozenset(TeamPermission)


def test_marker_marks_regrades_and_reads() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.MARKER] == frozenset(
        {TeamPermission.MARK, TeamPermission.REGRADE, TeamPermission.VIEW_RESULTS}
    )


def test_viewer_is_read_only() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.VIEWER] == frozenset(
        {TeamPermission.VIEW_RESULTS, TeamPermission.VIEW_USAGE}
    )


def test_every_role_has_a_preset() -> None:
    assert set(PRESET_PERMISSIONS) == set(AssistantRole)


def test_override_grants_a_permission() -> None:
    granted = effective_permissions(AssistantRole.VIEWER, {"manage_classes": True})
    assert TeamPermission.MANAGE_CLASSES in granted
    assert TeamPermission.VIEW_RESULTS in granted


def test_override_revokes_a_permission() -> None:
    granted = effective_permissions(AssistantRole.CO_TEACHER, {"mark": False})
    assert TeamPermission.MARK not in granted
    assert TeamPermission.REGRADE in granted


def test_role_may_be_a_plain_string() -> None:
    assert effective_permissions("marker", {}) == PRESET_PERMISSIONS[AssistantRole.MARKER]


@pytest.mark.parametrize("key", ["billing", "manage_seats", "manage_assistants", "plan"])
def test_unknown_override_keys_are_refused(key: str) -> None:
    with pytest.raises(UnknownPermissionError):
        validate_overrides({key: True})
    with pytest.raises(UnknownPermissionError):
        effective_permissions(AssistantRole.CO_TEACHER, {key: True})


def test_non_boolean_override_is_refused() -> None:
    with pytest.raises(UnknownPermissionError):
        validate_overrides({"mark": "yes"})


def test_validate_overrides_returns_a_sorted_clean_copy() -> None:
    result = validate_overrides({"regrade": False, "mark": True})
    assert result == {"mark": True, "regrade": False}
    assert list(result) == ["mark", "regrade"]
