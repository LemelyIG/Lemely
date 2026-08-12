"""Per-user notification preference storage (G-12, P3.6 chunk B).

Mirrors :class:`~lemely.db.parent_repo.ParentLinkService`'s shape directly:
``sessionmaker`` injection, a ``ValueError`` on a malformed UUID, a frozen
dataclass row. This module is the single ``notification_preferences`` query
in the codebase — no route may query that table directly.

**This module stores preferences; it does not deliver notifications.**
Nothing here decides whether a given notification would currently be sent,
including against the quiet-hours window — that decision belongs to P5,
which owns notification delivery end to end. Building a "would this be
delivered" helper here would be speculating on P5's design.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lemely.db.models import NotificationPreference

if TYPE_CHECKING:
    from datetime import time

    from sqlalchemy.orm import Session, sessionmaker


class _UnsetType:
    """Sentinel marking a :meth:`NotificationPreferencesService.set` keyword as not supplied.

    "Not supplied" means "leave unchanged". Distinct from an explicit
    ``None``: ``None`` is a legitimate value for
    ``quiet_hours_start``/``quiet_hours_end`` (it clears that bound), so
    "the caller didn't mention this field" needs its own marker rather than
    overloading ``None`` for both meanings.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


#: Sentinel default for every keyword of :meth:`NotificationPreferencesService.set`.
UNSET: Final = _UnsetType()


@dataclass(frozen=True, slots=True)
class NotificationPreferencesRow:
    """One user's notification preferences (or the all-defaults value).

    One field per :class:`~lemely.db.models.enums.NotificationType` member —
    kept in lockstep with the DB columns by
    ``tests/test_db_schema.py``'s ``test_notification_type_enum_matches_preference_columns``
    (P3.5 chunk A's three-way vocabulary-pin pattern) — plus the quiet-hours
    pair. Both quiet-hours fields ``None`` means "no quiet hours configured".
    The dataclass defaults double as the all-defaults value a caller with no
    stored row reads (see :data:`DEFAULTS`).
    """

    grade_ready: bool = True
    announcement: bool = True
    streak_warning: bool = True
    study_plan_reminder: bool = True
    at_risk_alert: bool = True
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


#: Returned by :meth:`NotificationPreferencesService.get` for a user with no row.
DEFAULTS: Final = NotificationPreferencesRow()


class NotificationPreferencesService:
    """Notification-preferences model service (one row per user).

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.parent_repo.ParentLinkService`). Every method re-derives
    its result from ``notification_preferences`` directly.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    def get(self, user_id: uuid.UUID | str) -> NotificationPreferencesRow:
        """Return ``user_id``'s preferences, or :data:`DEFAULTS` if no row exists.

        **Never creates a row.** A GET must not have a write side effect —
        "every type enabled, no quiet hours" is a safe, honest default that
        needs no persisted row to express.
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            row = session.get(NotificationPreference, uid)
            if row is None:
                return DEFAULTS
            return _row_from_model(row)

    def set(
        self,
        user_id: uuid.UUID | str,
        *,
        grade_ready: bool | _UnsetType = UNSET,
        announcement: bool | _UnsetType = UNSET,
        streak_warning: bool | _UnsetType = UNSET,
        study_plan_reminder: bool | _UnsetType = UNSET,
        at_risk_alert: bool | _UnsetType = UNSET,
        quiet_hours_start: time | _UnsetType | None = UNSET,
        quiet_hours_end: time | _UnsetType | None = UNSET,
    ) -> NotificationPreferencesRow:
        """Upsert ``user_id``'s preferences. Keywords left at :data:`UNSET` are untouched.

        A first call for a user upserts against :data:`DEFAULTS`, so a
        partial update from a brand-new user still lands every unmentioned
        field at its documented default rather than a raw ``NULL``. A later
        partial call merges onto the existing stored row, so unmentioned
        fields survive unchanged — this is what makes the update genuinely
        partial rather than a merge-with-defaults on every call.

        Raises:
            ValueError: the merged result would leave exactly one of
                ``quiet_hours_start``/``quiet_hours_end`` set. Both bounds or
                neither is the only representable state.
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            model_row = session.get(NotificationPreference, uid)
            current = _row_from_model(model_row) if model_row is not None else DEFAULTS
            merged = NotificationPreferencesRow(
                grade_ready=(
                    current.grade_ready if isinstance(grade_ready, _UnsetType) else grade_ready
                ),
                announcement=(
                    current.announcement if isinstance(announcement, _UnsetType) else announcement
                ),
                streak_warning=(
                    current.streak_warning
                    if isinstance(streak_warning, _UnsetType)
                    else streak_warning
                ),
                study_plan_reminder=(
                    current.study_plan_reminder
                    if isinstance(study_plan_reminder, _UnsetType)
                    else study_plan_reminder
                ),
                at_risk_alert=(
                    current.at_risk_alert
                    if isinstance(at_risk_alert, _UnsetType)
                    else at_risk_alert
                ),
                quiet_hours_start=(
                    current.quiet_hours_start
                    if isinstance(quiet_hours_start, _UnsetType)
                    else quiet_hours_start
                ),
                quiet_hours_end=(
                    current.quiet_hours_end
                    if isinstance(quiet_hours_end, _UnsetType)
                    else quiet_hours_end
                ),
            )
            if (merged.quiet_hours_start is None) != (merged.quiet_hours_end is None):
                raise ValueError(
                    "quiet_hours_start and quiet_hours_end must be set (or cleared) together"
                )
            if model_row is None:
                model_row = NotificationPreference(user_id=uid)
                session.add(model_row)
            model_row.grade_ready = merged.grade_ready
            model_row.announcement = merged.announcement
            model_row.streak_warning = merged.streak_warning
            model_row.study_plan_reminder = merged.study_plan_reminder
            model_row.at_risk_alert = merged.at_risk_alert
            model_row.quiet_hours_start = merged.quiet_hours_start
            model_row.quiet_hours_end = merged.quiet_hours_end
            session.flush()
            return merged


def _row_from_model(model: NotificationPreference) -> NotificationPreferencesRow:
    return NotificationPreferencesRow(
        grade_ready=model.grade_ready,
        announcement=model.announcement,
        streak_warning=model.streak_warning,
        study_plan_reminder=model.study_plan_reminder,
        at_risk_alert=model.at_risk_alert,
        quiet_hours_start=model.quiet_hours_start,
        quiet_hours_end=model.quiet_hours_end,
    )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "DEFAULTS",
    "UNSET",
    "NotificationPreferencesRow",
    "NotificationPreferencesService",
]
