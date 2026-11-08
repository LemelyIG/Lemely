"""Assistant roles and team permissions (spec §2.3, §7). Pure: no DB, no IO.

An assistant acts on the lead teacher's resources only when the effective permission
set of their ``teacher_members`` row grants the permission a route asks for
(``lemely.web.deps.require_team_permission``). The set is the role preset with the
row's per-permission toggles applied on top.

Billing, plan changes, seats, caps and assistants are never permissions. No value of
:class:`TeamPermission` names them, so no toggle can grant them. Those routes stay
behind ``require_role(Role.teacher)`` and act only on the caller's own team.

:class:`AssistantRole` mirrors ``lemely.db.models.team.AssistantRole`` member for
member. ``lemely.db.models`` never imports ``lemely.core``, and this module stays
pure, so the enum is declared twice; ``tests/test_team_schema.py`` pins that the two
agree. Both are ``StrEnum``, so either converts to the other by value.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class AssistantRole(StrEnum):
    CO_TEACHER = "co_teacher"
    MARKER = "marker"
    VIEWER = "viewer"


class TeamPermission(StrEnum):
    MARK = "mark"
    REGRADE = "regrade"
    GENERATE_QUIZ = "generate_quiz"
    MANAGE_CLASSES = "manage_classes"
    VIEW_RESULTS = "view_results"
    MANAGE_STUDENTS = "manage_students"
    VIEW_USAGE = "view_usage"


PRESET_PERMISSIONS: Mapping[AssistantRole, frozenset[TeamPermission]] = MappingProxyType(
    {
        AssistantRole.CO_TEACHER: frozenset(TeamPermission),
        AssistantRole.MARKER: frozenset(
            {TeamPermission.MARK, TeamPermission.REGRADE, TeamPermission.VIEW_RESULTS}
        ),
        AssistantRole.VIEWER: frozenset({TeamPermission.VIEW_RESULTS, TeamPermission.VIEW_USAGE}),
    }
)
"""Spec §2.3. A marker also reads (``view_results``) so it can see what it marks."""

_PERMISSION_VALUES: frozenset[str] = frozenset(p.value for p in TeamPermission)


class UnknownPermissionError(ValueError):
    """An override names something that is not a :class:`TeamPermission`, or is not a bool."""


def validate_overrides(overrides: Mapping[str, object]) -> dict[str, bool]:
    """Return a sorted, checked copy of ``overrides``.

    Raises:
        UnknownPermissionError: A key is not a :class:`TeamPermission` value, or a
            value is not a bool.
    """
    clean: dict[str, bool] = {}
    for key, value in overrides.items():
        if key not in _PERMISSION_VALUES:
            raise UnknownPermissionError(f"Unknown team permission: {key!r}")
        if not isinstance(value, bool):
            raise UnknownPermissionError(f"Team permission {key!r} must be true or false")
        clean[key] = value
    return dict(sorted(clean.items()))


def effective_permissions(
    role: AssistantRole | str, overrides: Mapping[str, bool]
) -> frozenset[TeamPermission]:
    """Return the role preset with ``overrides`` applied (``True`` grants, ``False`` revokes).

    Raises:
        ValueError: ``role`` is not an assistant role.
        UnknownPermissionError: See :func:`validate_overrides`.
    """
    granted = set(PRESET_PERMISSIONS[AssistantRole(role)])
    for key, allowed in validate_overrides(overrides).items():
        permission = TeamPermission(key)
        if allowed:
            granted.add(permission)
        else:
            granted.discard(permission)
    return frozenset(granted)


__all__ = [
    "PRESET_PERMISSIONS",
    "AssistantRole",
    "TeamPermission",
    "UnknownPermissionError",
    "effective_permissions",
    "validate_overrides",
]
