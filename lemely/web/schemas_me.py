"""``/api/me`` DTOs — notification preferences (G-12, P3.6 chunk B).

Wire format for ``GET``/``PUT /api/me/notification-preferences``
(``lemely.web.routers.me``), available to every authenticated role. Field
names mirror :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesRow`
one-for-one, camelCased.
"""

from __future__ import annotations

from datetime import time

from pydantic import Field

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


class ProfileDTO(ApiModel):
    """Response for ``GET /api/me/profile`` (P3.7 chunk B).

    Backs the teacher-portal sidebar identity block, which previously
    hardcoded a name and department no field anywhere supplies. Every field
    is real: ``displayName``/``email`` mirror :class:`~lemely.db.models.users.User`
    one-for-one (never a token claim, which may be stale or absent);
    ``role`` is the platform role the caller's token already carries.
    ``displayName`` is nullable — :attr:`User.display_name` is nullable in
    the schema (a user who never set one) — and the caller must render that
    absence honestly (e.g. the email's local part, or the role), never a
    fabricated name.

    ``emailVerified`` is ``users.email_verified_at is not None`` and nothing
    more. D7.5's soft gate (:func:`~lemely.web.deps.require_verified_email`)
    reads that column to refuse ``POST /api/student/correct``, and until this
    field existed no route and no token claim published the fact, so the app
    could only discover it by being refused. A boolean rather than the
    timestamp on purpose: the client only ever asks the yes/no question, and
    publishing the date would invite a screen to render it as a user-facing
    fact that then has to be maintained as one.

    ``avatarUrl`` is a freshly-signed, time-limited URL derived from
    ``users.avatar_path`` (never the stored path itself, and never cached
    beyond the response TTL) — ``null`` when no avatar is set, and also
    ``null`` (never a 500) when storage cannot be reached to sign one: the
    sidebar this DTO backs must render *something* even when object storage is
    down, per :func:`~lemely.web.routers.me._avatar_url_for`.

    ``timezone``/``timezoneIsExplicit`` mirror ``users.timezone`` and
    ``users.timezone_is_explicit`` (push-delivery spec §3). ``timezone`` is
    ``null`` when never set; the client renders that as "follow this device"
    and never invents a name for the server-side default.
    """

    displayName: str | None = None
    email: str
    role: str
    emailVerified: bool
    avatarUrl: str | None = None
    timezone: str | None = None
    timezoneIsExplicit: bool = False


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


class TimezoneUpdateDTO(ApiModel):
    """Body for ``PUT /api/me/timezone`` (push-delivery spec §3).

    ``timezone`` is an IANA name or ``null``; ``max_length=64`` matches the
    column. ``explicit`` says whether the *user* chose it: the settings picker
    sends ``true``, the app-boot auto-detect sends ``false``, and
    ``{"timezone": null, "explicit": false}`` is "follow this device" — the
    one body that clears an earlier choice. See the route for the full table.
    """

    timezone: str | None = Field(default=None, max_length=64)
    explicit: bool


class TimezoneDTO(ApiModel):
    """Response for ``PUT /api/me/timezone``: the stored state after the write.

    Echoes what is *stored*, not what was sent — a non-explicit write against
    a chosen zone changes nothing, and the response says so.
    """

    timezone: str | None
    timezoneIsExplicit: bool


__all__ = [
    "NotificationPreferencesDTO",
    "NotificationPreferencesUpdateDTO",
    "ProfileDTO",
    "TimezoneDTO",
    "TimezoneUpdateDTO",
]
