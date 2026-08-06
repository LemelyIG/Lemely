"""``/api/me`` DTOs — notification preferences (G-12, P3.6 chunk B).

Wire format for ``GET``/``PUT /api/me/notification-preferences``
(``lemely.web.routers.me``), available to every authenticated role. Field
names mirror :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesRow`
one-for-one, camelCased.
"""

from __future__ import annotations

from datetime import time

from lemely.web.schemas import ApiModel


class NotificationPreferencesDTO(ApiModel):
    """Full notification-preferences state — the ``GET`` response and ``PUT`` echo.

    One field per :class:`~lemely.db.models.enums.NotificationType` member,
    plus the quiet-hours pair. ``atRiskAlert`` is ``null`` for every role
    except teacher/parent (UI spec §G-12: "teacher/at-risk alerts (teacher
    and parent only)") — ``lemely.web.routers.me`` decides the filtering;
    this DTO just carries the optional value.
    """

    gradeReady: bool
    announcement: bool
    streakWarning: bool
    studyPlanReminder: bool
    atRiskAlert: bool | None = None
    quietHoursStart: time | None = None
    quietHoursEnd: time | None = None


class NotificationPreferencesUpdateDTO(ApiModel):
    """Body for ``PUT /api/me/notification-preferences``. Every field is optional.

    A genuine partial update: a field omitted from the request body is left
    untouched server-side, which the router distinguishes from "explicitly
    supplied" via pydantic's ``model_fields_set``. This matters for
    ``atRiskAlert`` (role-gated — omission is never an error, explicit
    provision by a disallowed role is) and for the quiet-hours pair (an
    explicit ``null`` clears that bound; omission leaves it as-is).
    """

    gradeReady: bool | None = None
    announcement: bool | None = None
    streakWarning: bool | None = None
    studyPlanReminder: bool | None = None
    atRiskAlert: bool | None = None
    quietHoursStart: time | None = None
    quietHoursEnd: time | None = None


__all__ = ["NotificationPreferencesDTO", "NotificationPreferencesUpdateDTO"]
