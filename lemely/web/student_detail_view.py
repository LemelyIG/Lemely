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

An instant that cannot be placed on a day in the tutor's zone (unparseable, or
without an offset) is shown as ``""``: nothing about it is passed on.

The route-level test ``test_t20_equals_projection_of_teacher_route`` proves that
T20's ``detail`` is :func:`project_for_tutor` of the teacher route's response
(acknowledgements removed) for one seeded student.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from lemely.db.class_repo import RosterEntry
from lemely.web.routers.teacher import _student_detail_dto

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from lemely.core.history import StudentHistory
    from lemely.web.schemas_analytics import StudentDetailDTO
    from lemely.web.schemas_teacher import AtRiskFlagDTO


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
    (F12: never the email fallback the roster uses). ``zone`` is the tutor's.
    """
    dto = _student_detail_dto(
        RosterEntry(student_id=student_id, display_name=display_name),
        history,
        now=now,
        acks={},
        targets=targets,
    )
    return project_for_tutor(dto, zone=zone)


def project_for_tutor(dto: StudentDetailDTO, *, zone: str) -> StudentDetailDTO:
    """``dto`` with instants cut to days in ``zone``, no question ids and no acknowledgements.

    Returns a new DTO; ``dto`` is left unchanged.
    """
    tz = ZoneInfo(zone)
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
            "atRiskFlags": [_project_flag(flag, tz) for flag in dto.atRiskFlags],
            "engagement": dto.engagement.model_copy(
                update={
                    "lastActiveAt": (
                        tutor_day(dto.engagement.lastActiveAt, tz)
                        if dto.engagement.lastActiveAt is not None
                        else None
                    )
                }
            ),
        }
    )


def tutor_day(value: str, tz: ZoneInfo) -> str:
    """The ISO calendar day of instant ``value`` in ``tz``; ``""`` when it cannot be placed."""
    instant = _instant(value)
    return instant.astimezone(tz).date().isoformat() if instant is not None else ""


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


__all__ = ["build_student_detail_for_tutor", "project_for_tutor", "tutor_day"]
