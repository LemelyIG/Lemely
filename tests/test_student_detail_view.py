"""The tutor projection of the T-05 student detail (SPEC §e.2, SC-20, ID-9; ADR-T02).

A granted tutor sees the teacher builder's output with every instant cut down to
its day in the tutor's zone, no question ids and no teacher acknowledgements.
The S-38 explainer promises the student exactly that: "never the time of day you
used Lemely" (F29).

The red cases are real routines: a paper submitted at 23:40 UTC is 01:40 or
02:40 the next day in Cairo, so a projection that kept the UTC date (anywhere,
including the at-risk summary sentence) would show the tutor that the student
works after midnight.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from lemely.core.at_risk import assess_at_risk, flag_fingerprint
from lemely.core.history import StudentHistory
from lemely.db.at_risk_repo import AtRiskAcknowledgementRow
from lemely.db.class_repo import RosterEntry
from lemely.web.routers.teacher import _student_detail_dto
from lemely.web.student_detail_view import build_student_detail_for_tutor, project_for_tutor
from tests.test_tutor_grant_repo import paper

CAIRO = "Africa/Cairo"
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
    assert tutor_view.engagement.daysSinceLastSubmission == (
        teacher_view.engagement.daysSinceLastSubmission
    )
    assert tutor_view.isAtRisk is teacher_view.isAtRisk


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

    projected = project_for_tutor(teacher_view, zone=CAIRO)

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
    in_utc = project_for_tutor(dto, zone="UTC")
    assert in_utc.attempts[0].recordedAt == "2026-09-30"
    in_cairo = project_for_tutor(dto, zone=CAIRO)
    assert in_cairo.attempts[0].recordedAt == (
        datetime(2026, 9, 30, 23, 40, tzinfo=UTC).astimezone(ZoneInfo(CAIRO)).date().isoformat()
    )

    # An instant that cannot be placed on a day in the tutor's zone shows nothing at all.
    naive = dto.model_copy(
        update={
            "attempts": [
                dto.attempts[0].model_copy(update={"recordedAt": "2026-09-30T23:40:00"}),
                dto.attempts[1].model_copy(update={"recordedAt": "not a time"}),
            ]
        }
    )
    assert [a.recordedAt for a in project_for_tutor(naive, zone=CAIRO).attempts] == ["", ""]


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
    project_for_tutor(dto, zone=CAIRO)
    assert dto.model_dump() == before
