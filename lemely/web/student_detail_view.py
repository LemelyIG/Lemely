"""The tutor projection of the T-05 student detail (SPEC §e.2, SC-20, ID-9; ADR-T02).

A tutor with a valid grant sees the same analytics a class teacher sees on T-05,
built by the same function (``teacher._student_detail_dto``, imported, never
edited, never copied), then minimised by :func:`project_for_tutor`:

* every instant (``attempts[].recordedAt``, ``trend[].recordedAt``,
  ``engagement.lastActiveAt`` and any instant in at-risk ``evidence``) becomes
  its calendar day in the tutor's zone (``tutor_profiles.zone``): the student's
  explainer promises "never the time of day you used Lemely" (F29), and a
  submission at 01:40 Cairo time is exactly what ID-9 protects;
* the at-risk summary sentence names that same day: the core rule writes the day
  of the instant's own offset (UTC), which would otherwise give a late-night
  session away next to the projected evidence;
* ``weaknesses[].questionIds`` are emptied (a tutor has no question routes);
* teacher acknowledgements are never carried (they name a teacher and a note).

**Day counts are calendar days** (lead decision at the T14 review). The teacher's
``engagement.daysSinceLastSubmission`` and the inactive flag's ``daysInactive``
count elapsed 24-hour periods, so their value changes at the hour of the last
activity, and a tutor who reads twice a day could bisect that hour from the
audited reads. For the tutor both are the difference between two calendar days
in the tutor's zone, today's (from ``now``, the instant the route read) and the
last activity's, so every read on one tutor day gives the same DTO. The inactive
flag follows that count alone: the tutor sees it exactly when the count is at
least :data:`TUTOR_INACTIVE_DAYS` (15), rebuilt from the projected day and count.
Fifteen calendar days are 14 elapsed days or more at any hour, except across a
spring-forward night, where they can fall short by the size of the clock change
(an hour in Cairo); the teacher's flag has then not fired yet, so the tutor's
flag is rebuilt rather than kept or dropped (copying the teacher's would make it
appear between two reads of one day and date the activity to the minute).
``isAtRisk`` is recomputed from the flags the tutor sees. The teacher route's own
numbers are untouched: this module works on a copy of the teacher DTO.

An instant that cannot be placed on a day in the tutor's zone (unparseable, or
without an offset) is shown as ``""`` and counts nothing: nothing about it is
passed on.

The route-level test ``test_t20_equals_projection_of_teacher_route`` proves that
T20's ``detail`` is :func:`project_for_tutor` of the teacher route's response
(acknowledgements removed) for one seeded student.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from lemely.db.class_repo import RosterEntry
from lemely.web.routers.teacher import _student_detail_dto
from lemely.web.schemas_teacher import AtRiskFlagDTO

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from lemely.core.history import StudentHistory
    from lemely.web.schemas_analytics import StudentDetailDTO

#: The tutor sees the inactive flag once this many tutor-zone calendar days have
#: passed since the last activity (the core rule's 14 elapsed days, as a day count).
TUTOR_INACTIVE_DAYS: Final = 15
#: ``core.at_risk.AtRiskReason.INACTIVE`` as the DTO carries it.
_INACTIVE: Final = "inactive"


def build_student_detail_for_tutor(
    *,
    student_id: uuid.UUID,
    display_name: str,
    history: StudentHistory,
    now: datetime,
    targets: Mapping[str, str] | None,
    zone: str,
) -> StudentDetailDTO:
    """T-05's DTO for a granted tutor: the teacher builder's output, then the tutor projection.

    ``display_name`` must already be ``core.tutor_directory.student_label(...)``
    (F12: never the email fallback the roster uses). ``zone`` is the tutor's;
    ``now`` is the request's instant, passed to both steps.
    """
    dto = _student_detail_dto(
        RosterEntry(student_id=student_id, display_name=display_name),
        history,
        now=now,
        acks={},
        targets=targets,
    )
    return project_for_tutor(dto, zone=zone, now=now)


def project_for_tutor(dto: StudentDetailDTO, *, zone: str, now: datetime) -> StudentDetailDTO:
    """``dto`` with instants cut to days and day counts recounted in ``zone`` as of ``now``.

    Also empties question ids and drops acknowledgements. Returns a new DTO;
    ``dto`` is left unchanged.

    Raises:
        ValueError: ``now`` has no offset (its day in ``zone`` would be a guess).
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now must be a timezone-aware datetime, got naive {now!r}")
    tz = ZoneInfo(zone)
    last_active = dto.engagement.lastActiveAt
    last_day = tutor_day(last_active, tz) if last_active is not None else None
    days = calendar_days_between(last_active, now, tz) if last_active is not None else None
    flags = [_project_flag(flag, tz) for flag in dto.atRiskFlags if flag.reason != _INACTIVE]
    if days is not None and last_day and days >= TUTOR_INACTIVE_DAYS:
        flags.append(_inactive_flag(days, last_day))
    return dto.model_copy(
        update={
            "attempts": [
                attempt.model_copy(update={"recordedAt": tutor_day(attempt.recordedAt, tz)})
                for attempt in dto.attempts
            ],
            "trend": [
                point.model_copy(update={"recordedAt": tutor_day(point.recordedAt, tz)})
                for point in dto.trend
            ],
            "weaknesses": [
                weakness.model_copy(update={"questionIds": []}) for weakness in dto.weaknesses
            ],
            "isAtRisk": bool(flags),
            "atRiskFlags": flags,
            "engagement": dto.engagement.model_copy(
                update={"lastActiveAt": last_day, "daysSinceLastSubmission": days}
            ),
        }
    )


def tutor_zone_day(instant: datetime, zone: str) -> str:
    """The ISO calendar day of ``instant`` in ``zone``: how T19 and T20 send ``grantedAt``.

    The hour a student shared their data is theirs (ID-9, F30-4), so the tutor gets the day.

    Raises:
        ValueError: ``instant`` has no offset (its day in ``zone`` would be a guess).
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"instant must be a timezone-aware datetime, got naive {instant!r}")
    return instant.astimezone(ZoneInfo(zone)).date().isoformat()


def tutor_day(value: str, tz: ZoneInfo) -> str:
    """The ISO calendar day of instant ``value`` in ``tz``; ``""`` when it cannot be placed."""
    instant = _instant(value)
    return instant.astimezone(tz).date().isoformat() if instant is not None else ""


def calendar_days_between(value: str, now: datetime, tz: ZoneInfo) -> int | None:
    """Calendar days from instant ``value``'s day to ``now``'s day, both in ``tz``.

    ``None`` when ``value`` cannot be placed. The same for any two instants on the
    same pair of days, whatever their hours.
    """
    instant = _instant(value)
    if instant is None:
        return None
    return (now.astimezone(tz).date() - instant.astimezone(tz).date()).days


def _instant(value: str) -> datetime | None:
    """``value`` as an aware instant, or ``None`` (not an instant, or no offset)."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _looks_like_time(value: str) -> bool:
    """Whether ``value`` parses as a date or time at all (aware or not)."""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _inactive_flag(days: int, last_day: str) -> AtRiskFlagDTO:
    """The inactive flag as the tutor sees it: the tutor-day count and the tutor day only."""
    return AtRiskFlagDTO(
        reason=_INACTIVE,
        summary=f"No papers submitted in {days} days (last active {last_day}).",
        evidence={"daysInactive": days, "lastActiveAt": last_day},
        acknowledged=None,
    )


def _project_flag(flag: AtRiskFlagDTO, tz: ZoneInfo) -> AtRiskFlagDTO:
    """One at-risk flag with its instants cut to days, in the evidence and in the summary."""
    evidence: dict[str, float | int | str | list[float]] = {}
    summary = flag.summary
    for key, value in flag.evidence.items():
        if isinstance(value, str) and _looks_like_time(value):
            day = tutor_day(value, tz)
            instant = _instant(value)
            # The core sentence prints the instant itself or its day in its own offset.
            summary = summary.replace(value, day)
            if instant is not None:
                summary = summary.replace(instant.date().isoformat(), day)
            evidence[key] = day
        else:
            evidence[key] = value
    return flag.model_copy(update={"evidence": evidence, "summary": summary, "acknowledged": None})


__all__ = [
    "TUTOR_INACTIVE_DAYS",
    "build_student_detail_for_tutor",
    "calendar_days_between",
    "project_for_tutor",
    "tutor_day",
    "tutor_zone_day",
]
