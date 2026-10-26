"""The tutor projection of the T-05 student detail (SPEC §e.2, SC-20, ID-9; ADR-T02).

A granted tutor sees the teacher builder's output with every instant cut down to
its day in the tutor's zone, no question ids and no teacher acknowledgements.
The S-38 explainer promises the student exactly that: "never the time of day you
used Lemely" (F29).

The red cases are real routines: a paper submitted at 23:40 UTC is 01:40 or
02:40 the next day in Cairo, so a projection that kept the UTC date (anywhere,
including the at-risk summary sentence) would show the tutor that the student
works after midnight.

Day counts are the same kind of leak (lead decision at the T14 review): an
elapsed-day count changes at the hour of the last activity, so a tutor reading
twice a day could bisect that hour. The tutor's counts are differences between
tutor-zone calendar days, and the inactive flag follows that count alone.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lemely.core.at_risk import assess_at_risk, flag_fingerprint
from lemely.core.history import StudentHistory
from lemely.db.at_risk_repo import AtRiskAcknowledgementRow
from lemely.db.class_repo import RosterEntry
from lemely.web.routers.teacher import _student_detail_dto
from lemely.web.schemas_analytics import StudentDetailDTO
from lemely.web.student_detail_view import build_student_detail_for_tutor, project_for_tutor
from tests.test_tutor_grant_repo import paper

CAIRO = "Africa/Cairo"
CAIRO_TZ = ZoneInfo(CAIRO)
TARGETS = {"0625": "A"}
#: Any clock time (``HH:MM``) or ISO instant separator in a serialised value.
_TIME_OF_DAY = re.compile(r"\d{2}:\d{2}|T\d{2}")


def _history(student: uuid.UUID, last: datetime) -> StudentHistory:
    """Three declining papers, the last at ``last`` and 14 days apart."""
    records = [
        paper(student, recorded_at=last - timedelta(days=28), percentage=80.0, grade="B"),
        paper(student, recorded_at=last - timedelta(days=14), percentage=70.0, grade="C"),
        paper(student, recorded_at=last, percentage=55.0, grade="E"),
    ]
    return StudentHistory(student_id=str(student), records=records)


def _teacher_view(
    student: uuid.UUID, history: StudentHistory, now: datetime, targets: dict[str, str] | None
) -> StudentDetailDTO:
    return _student_detail_dto(
        RosterEntry(student_id=student, display_name="Amelia"),
        history,
        now=now,
        acks={},
        targets=targets,
    )


def _tutor_view(
    student: uuid.UUID, history: StudentHistory, now: datetime, targets: dict[str, str] | None
) -> StudentDetailDTO:
    return build_student_detail_for_tutor(
        student_id=student,
        display_name="Amelia",
        history=history,
        now=now,
        targets=targets,
        zone=CAIRO,
    )


def _reasons(dto: StudentDetailDTO) -> list[str]:
    return [flag.reason for flag in dto.atRiskFlags]


def _strings(value: object) -> list[str]:
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return [value] if isinstance(value, str) else []


def test_privacy_tutor_projection_truncates_timestamps_and_drops_question_ids() -> None:
    student = uuid.uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    last = datetime(2026, 9, 30, 23, 40, tzinfo=UTC)  # 02:40 on 1 October in Cairo
    history = _history(student, last)

    teacher_view = _student_detail_dto(
        RosterEntry(student_id=student, display_name="Amelia"),
        history,
        now=now,
        acks={},
        targets={"0625": "A"},
    )
    tutor_view = build_student_detail_for_tutor(
        student_id=student,
        display_name="Amelia",
        history=history,
        now=now,
        targets={"0625": "A"},
        zone=CAIRO,
    )

    # Red case: the teacher's view really does carry the time and the question ids.
    assert teacher_view.attempts[0].recordedAt == last.isoformat()
    assert teacher_view.weaknesses[0].questionIds
    assert any(_TIME_OF_DAY.search(s) for s in _strings(teacher_view.model_dump()))

    cairo_day = "2026-10-01"
    assert [a.recordedAt for a in tutor_view.attempts] == [cairo_day, "2026-09-17", "2026-09-03"]
    assert [t.recordedAt for t in tutor_view.trend] == ["2026-09-03", "2026-09-17", cairo_day]
    assert tutor_view.engagement.lastActiveAt == cairo_day
    assert all(w.questionIds == [] for w in tutor_view.weaknesses)
    assert tutor_view.weaknesses  # the weakness itself stays

    reasons = {flag.reason: flag for flag in tutor_view.atRiskFlags}
    assert set(reasons) == {"declining_trend", "below_target", "inactive"}
    inactive = reasons["inactive"]
    assert inactive.evidence["lastActiveAt"] == cairo_day
    # The summary sentence names the same Cairo day, never the UTC one (30 September).
    assert cairo_day in inactive.summary
    assert "2026-09-30" not in inactive.summary
    assert "2026-09-30" in next(
        f.summary for f in teacher_view.atRiskFlags if f.reason == "inactive"
    )

    # Nothing anywhere in the tutor's view says what time of day anything happened.
    assert not [s for s in _strings(tutor_view.model_dump()) if _TIME_OF_DAY.search(s)]
    # Everything that is not a time is the teacher's view unchanged.
    assert tutor_view.subjects == teacher_view.subjects
    assert [a.percentage for a in tutor_view.attempts] == [
        a.percentage for a in teacher_view.attempts
    ]
    # Counted by hand: 26 October (15:00 in Cairo) minus 1 October (Cairo) is 25 calendar days.
    assert tutor_view.engagement.daysSinceLastSubmission == 25
    assert inactive.evidence["daysInactive"] == 25
    assert inactive.summary == "No papers submitted in 25 days (last active 2026-10-01)."
    assert tutor_view.isAtRisk is True


def test_projection_drops_teacher_acknowledgements() -> None:
    student = uuid.uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    history = _history(student, datetime(2026, 9, 30, 9, 0, tzinfo=UTC))
    assessment = assess_at_risk(history, now=now, targets=None)
    flag = assessment.flags[0]
    ack = AtRiskAcknowledgementRow(
        student_id=student,
        reason=flag.reason,
        evidence_fingerprint=flag_fingerprint(flag),
        note="Spoke to the family",
        acknowledged_by=uuid.uuid4(),
        acknowledged_at=now,
    )
    teacher_view = _student_detail_dto(
        RosterEntry(student_id=student, display_name="Amelia"),
        history,
        now=now,
        acks={(str(student), flag.reason): ack},
    )
    assert teacher_view.atRiskFlags[0].acknowledged is not None  # red case

    projected = project_for_tutor(teacher_view, zone=CAIRO, now=now)

    assert all(f.acknowledged is None for f in projected.atRiskFlags)
    assert "Spoke to the family" not in projected.model_dump_json()


def test_projection_uses_the_tutors_zone_and_refuses_unplaceable_instants() -> None:
    student = uuid.uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    history = _history(student, datetime(2026, 9, 30, 23, 40, tzinfo=UTC))
    dto = _student_detail_dto(
        RosterEntry(student_id=student, display_name="Amelia"), history, now=now, acks={}
    )
    # The same instant is another day in another zone: the zone is the tutor's, not fixed.
    in_utc = project_for_tutor(dto, zone="UTC", now=now)
    assert in_utc.attempts[0].recordedAt == "2026-09-30"
    assert in_utc.engagement.daysSinceLastSubmission == 26  # 26 October - 30 September
    in_cairo = project_for_tutor(dto, zone=CAIRO, now=now)
    assert in_cairo.attempts[0].recordedAt == (
        datetime(2026, 9, 30, 23, 40, tzinfo=UTC).astimezone(ZoneInfo(CAIRO)).date().isoformat()
    )
    assert in_cairo.engagement.daysSinceLastSubmission == 25  # 26 October - 1 October

    # An instant that cannot be placed on a day in the tutor's zone shows nothing at all.
    naive = dto.model_copy(
        update={
            "attempts": [
                dto.attempts[0].model_copy(update={"recordedAt": "2026-09-30T23:40:00"}),
                dto.attempts[1].model_copy(update={"recordedAt": "not a time"}),
            ]
        }
    )
    assert [a.recordedAt for a in project_for_tutor(naive, zone=CAIRO, now=now).attempts] == [
        "",
        "",
    ]
    # Nor does its day count, and no inactive flag can stand on it.
    for unplaceable in ("2026-09-30T23:40:00", "not a time"):
        hidden = project_for_tutor(
            dto.model_copy(
                update={
                    "engagement": dto.engagement.model_copy(update={"lastActiveAt": unplaceable})
                }
            ),
            zone=CAIRO,
            now=now,
        )
        assert hidden.engagement.lastActiveAt == ""
        assert hidden.engagement.daysSinceLastSubmission is None
        assert "inactive" not in _reasons(hidden)
    # A clock without an offset is a programming error, never guessed at.
    with pytest.raises(ValueError, match="now"):
        project_for_tutor(dto, zone=CAIRO, now=now.replace(tzinfo=None))


def test_projection_leaves_the_input_untouched() -> None:
    student = uuid.uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    dto = _student_detail_dto(
        RosterEntry(student_id=student, display_name="Amelia"),
        _history(student, datetime(2026, 9, 30, 23, 40, tzinfo=UTC)),
        now=now,
        acks={},
    )
    before = dto.model_dump()
    project_for_tutor(dto, zone=CAIRO, now=now)
    assert dto.model_dump() == before


# ---------------------------------------------------------------------------
# Day counts: a function of the tutor's day, never of the hour (ID-9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("days_apart", "flagged"), [(14, False), (15, True)])
def test_projection_is_a_function_of_the_tutor_day(days_apart: int, flagged: bool) -> None:
    """Last active at 00:10 or 23:50 on 1 December, read at 00:05 or 23:55 ``days_apart`` later.

    Cairo keeps one offset all December, so the four reads span elapsed times that
    straddle whole days (13 d 0 h 15 m up to 15 d 23 h 45 m), yet name one pair of
    tutor days: the tutor gets one DTO, so repeated reads say nothing about the hour.
    """
    student = uuid.uuid4()
    first_day = datetime(2026, 12, 1, tzinfo=CAIRO_TZ)
    read_day = first_day + timedelta(days=days_apart)
    lasts = (first_day.replace(hour=0, minute=10), first_day.replace(hour=23, minute=50))
    nows = (read_day.replace(hour=0, minute=5), read_day.replace(hour=23, minute=55))
    combos = [(_history(student, last), now) for last in lasts for now in nows]

    teacher = [_teacher_view(student, history, now, TARGETS) for history, now in combos]
    tutor = [_tutor_view(student, history, now, TARGETS).model_dump() for history, now in combos]

    # Red case: the teacher's elapsed counts behind these four reads really differ.
    assert len({t.engagement.daysSinceLastSubmission for t in teacher}) == 2
    assert len({tuple(_reasons(t)) for t in teacher}) == (2 if days_apart == 14 else 1)
    assert tutor[1:] == [tutor[0]] * 3
    view = tutor[0]
    assert view["engagement"]["daysSinceLastSubmission"] == days_apart
    assert view["engagement"]["lastActiveAt"] == "2026-12-01"
    inactive = [flag for flag in view["atRiskFlags"] if flag["reason"] == "inactive"]
    if flagged:
        assert inactive == [
            {
                "reason": "inactive",
                "summary": "No papers submitted in 15 days (last active 2026-12-01).",
                "evidence": {"daysInactive": 15, "lastActiveAt": "2026-12-01"},
                "acknowledged": None,
            }
        ]
    else:
        assert inactive == []
    # The other two rules fire on every read, so the student stays at risk either way.
    assert [f["reason"] for f in view["atRiskFlags"]][:2] == ["declining_trend", "below_target"]
    assert view["isAtRisk"] is True


def test_dropped_inactive_flag_leaves_the_student_not_at_risk() -> None:
    """``isAtRisk`` is recomputed from the flags the tutor sees, not copied from the teacher."""
    student = uuid.uuid4()
    last = datetime(2026, 12, 1, 0, 10, tzinfo=CAIRO_TZ)
    now = datetime(2026, 12, 15, 23, 55, tzinfo=CAIRO_TZ)  # 14 d 23 h 45 m, 14 tutor days
    history = StudentHistory(
        student_id=str(student),
        records=[paper(student, recorded_at=last, percentage=70.0, grade="C")],
    )

    teacher = _teacher_view(student, history, now, None)
    tutor = _tutor_view(student, history, now, None)

    assert _reasons(teacher) == ["inactive"]  # red case: only the inactivity rule fired
    assert teacher.isAtRisk is True
    assert tutor.atRiskFlags == []
    assert tutor.isAtRisk is False
    assert tutor.engagement.daysSinceLastSubmission == 14


def test_inactive_flag_follows_the_tutor_day_across_spring_forward() -> None:
    """Cairo skips 00:00-01:00 on 24 April 2026, so 15 tutor days can be under 14 x 24 h.

    Last active 23:50 on 15 April; read at 00:30 and at 23:55 on 30 April. The early
    read is 13 d 23 h 40 m after the activity, so the teacher's rule has not fired
    yet, and copying the teacher's flag would make it appear between the two reads
    and give away the minute. The tutor's flag follows the 15-day count alone.
    """
    student = uuid.uuid4()
    last = datetime(2026, 4, 15, 23, 50, tzinfo=CAIRO_TZ)
    early = datetime(2026, 4, 30, 0, 30, tzinfo=CAIRO_TZ)
    late = datetime(2026, 4, 30, 23, 55, tzinfo=CAIRO_TZ)
    history = _history(student, last)
    # The premise: one fewer hour in between, and the teacher's flag absent, then present.
    assert early.astimezone(UTC) - last.astimezone(UTC) == timedelta(days=13, hours=23, minutes=40)
    assert "inactive" not in _reasons(_teacher_view(student, history, early, TARGETS))
    assert "inactive" in _reasons(_teacher_view(student, history, late, TARGETS))

    views = [_tutor_view(student, history, now, TARGETS).model_dump() for now in (early, late)]

    assert views[0] == views[1]
    assert views[0]["engagement"]["daysSinceLastSubmission"] == 15
    [inactive] = [f for f in views[0]["atRiskFlags"] if f["reason"] == "inactive"]
    assert inactive["evidence"] == {"daysInactive": 15, "lastActiveAt": "2026-04-15"}
