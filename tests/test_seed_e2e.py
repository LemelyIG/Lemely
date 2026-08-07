"""Unit tests for the pure/derivable parts of ``scripts/seed_e2e.py`` (P3.10a).

Everything here is hermetic — no DB, no GoTrue, no wall clock (every scenario
supplies its own fixed ``now``), mirroring ``tests/test_at_risk.py``'s style.
The impure ``seed()`` orchestration (real GoTrue/Postgres I/O) is deliberately
NOT exercised here: verifying it needs the live migrated stack, and running a
full multi-role signup + OTP + attempt-persist flow on every ``pytest``
invocation would seed real demo rows every time a developer runs the suite
with the stack up — the opposite of what a seed script is for. That flow was
verified manually against the live stack (see the P3.10a chunk report).
"""

from __future__ import annotations

from datetime import UTC, datetime

from lemely.core.at_risk import AtRiskReason, assess_at_risk
from lemely.core.history import StudentHistory, is_grade_bearing
from scripts.seed_e2e import (
    CONTROL_SCORES,
    CORRECTED_SCORE,
    DECLINING_DAYS_AGO,
    DECLINING_SCORES,
    INACTIVE_SCORE,
    SUBJECT_CODE,
    accuracy_report_for_score,
    build_email,
    build_password,
    build_phone,
    build_result_payload,
    control_recorded_ats,
    corrected_recorded_at,
    declining_recorded_ats,
    default_run_tag,
    inactive_recorded_at,
    paper_record_for_scenario,
)

_NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Identity/credential builders.
# ---------------------------------------------------------------------------


class TestCredentialBuilders:
    def test_build_email_is_namespaced_by_role_and_tag(self) -> None:
        assert build_email("teacher", "abc123") == "teacher-abc123@e2e.lemely.local"

    def test_build_email_differs_across_roles_for_the_same_tag(self) -> None:
        assert build_email("teacher", "abc123") != build_email("admin", "abc123")

    def test_build_password_differs_across_tags(self) -> None:
        assert build_password("tag1") != build_password("tag2")

    def test_build_password_is_deterministic(self) -> None:
        assert build_password("tag1") == build_password("tag1")

    def test_build_phone_shape(self) -> None:
        phone = build_phone("abcdef123456")
        assert phone.startswith("+20")
        assert len(phone) == 13  # "+20" + 10 digits
        assert phone[3:].isdigit()

    def test_build_phone_is_deterministic(self) -> None:
        assert build_phone("sametag0000") == build_phone("sametag0000")

    def test_build_phone_differs_across_tags(self) -> None:
        assert build_phone("tag-one-000") != build_phone("tag-two-111")

    def test_default_run_tag_is_unique_per_call(self) -> None:
        tags = {default_run_tag() for _ in range(20)}
        assert len(tags) == 20

    def test_default_run_tag_is_lowercase_hex(self) -> None:
        tag = default_run_tag()
        assert len(tag) == 12
        int(tag, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# Date arithmetic.
# ---------------------------------------------------------------------------


class TestDateArithmetic:
    def test_declining_recorded_ats_are_oldest_first(self) -> None:
        ats = declining_recorded_ats(_NOW)
        assert ats == sorted(ats)
        assert len(ats) == len(DECLINING_DAYS_AGO) == 3

    def test_declining_recorded_ats_match_days_ago(self) -> None:
        ats = declining_recorded_ats(_NOW)
        for at, days_ago in zip(ats, DECLINING_DAYS_AGO, strict=True):
            assert (_NOW - at).days == days_ago

    def test_control_recorded_ats_are_oldest_first_and_recent(self) -> None:
        ats = control_recorded_ats(_NOW)
        assert ats == sorted(ats)
        assert all((_NOW - at).days < 14 for at in ats)

    def test_inactive_recorded_at_is_at_least_14_days_ago(self) -> None:
        at = inactive_recorded_at(_NOW)
        assert (_NOW - at).days >= 14

    def test_corrected_recorded_at_is_recent(self) -> None:
        at = corrected_recorded_at(_NOW)
        assert (_NOW - at).days < 14


# ---------------------------------------------------------------------------
# Scenario proof — feed the exact scores/dates the real seed persists into
# ``assess_at_risk`` directly, with no DB in the loop, and prove each fires
# (or doesn't) exactly as the seed's docstring claims.
# ---------------------------------------------------------------------------


class TestScenariosFireCorrectly:
    def test_declining_scenario_fires_declining_trend_only(self) -> None:
        records = [
            paper_record_for_scenario("declining", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(DECLINING_SCORES, declining_recorded_ats(_NOW), strict=True)
            )
        ]
        history = StudentHistory(student_id="declining", records=records)
        assessment = assess_at_risk(history, now=_NOW)
        reasons = {flag.reason for flag in assessment.flags}
        assert reasons == {AtRiskReason.DECLINING_TREND}

    def test_declining_run_is_a_single_subject(self) -> None:
        """Rule 1 reads the last 3 grade-bearing records across ALL subjects —
        a second subject interleaved into this run would stop it firing."""
        records = [
            paper_record_for_scenario("declining", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(DECLINING_SCORES, declining_recorded_ats(_NOW), strict=True)
            )
        ]
        assert {r.metadata.subject_code for r in records} == {SUBJECT_CODE}

    def test_inactive_scenario_fires_inactive_only(self) -> None:
        record = paper_record_for_scenario(
            "inactive", INACTIVE_SCORE, inactive_recorded_at(_NOW), paper_number=1
        )
        history = StudentHistory(student_id="inactive", records=[record])
        assessment = assess_at_risk(history, now=_NOW)
        reasons = {flag.reason for flag in assessment.flags}
        assert reasons == {AtRiskReason.INACTIVE}

    def test_control_scenario_is_never_flagged(self) -> None:
        records = [
            paper_record_for_scenario("control", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(CONTROL_SCORES, control_recorded_ats(_NOW), strict=True)
            )
        ]
        history = StudentHistory(student_id="control", records=records)
        assessment = assess_at_risk(history, now=_NOW)
        assert assessment.flags == []
        assert not assessment.is_at_risk

    def test_corrected_paper_record_is_grade_bearing(self) -> None:
        record = paper_record_for_scenario(
            "corrected", CORRECTED_SCORE, corrected_recorded_at(_NOW), paper_number=1
        )
        assert is_grade_bearing(record)


# ---------------------------------------------------------------------------
# accuracy_report_for_score — what actually gets persisted.
# ---------------------------------------------------------------------------


class TestAccuracyReportForScore:
    def test_carries_the_exact_percentage_and_grade(self) -> None:
        report = accuracy_report_for_score((66.5, "C"), paper_number=2)
        assert report.grade_prediction.percentage == 66.5
        assert report.grade_prediction.grade == "C"

    def test_uses_the_single_shared_subject_code(self) -> None:
        report = accuracy_report_for_score((66.5, "C"), paper_number=2)
        assert report.correction.metadata.subject_code == SUBJECT_CODE

    def test_paper_number_is_threaded_through(self) -> None:
        report = accuracy_report_for_score((50.0, "D"), paper_number=3)
        assert report.correction.metadata.paper_number == 3

    def test_never_needs_teacher_review(self) -> None:
        """A seed attempt must never land in the review queue — it isn't
        exercising that surface and would just be noise there."""
        report = accuracy_report_for_score((10.0, "U"), paper_number=1)
        assert report.correction.needs_teacher_review is False


# ---------------------------------------------------------------------------
# Output contract shape.
# ---------------------------------------------------------------------------


class TestBuildResultPayload:
    def test_shape_matches_the_documented_contract(self) -> None:
        payload = build_result_payload(
            run_tag="tag123",
            generated_at=_NOW,
            teacher={"userId": "t1"},
            school_admin={"userId": "a1"},
            class_row={"classId": "c1", "name": "n", "joinCode": "J1"},
            students={
                "declining": {"userId": "d1", "expectedAtRiskReasons": ["declining_trend"]},
                "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
                "control": {"userId": "c1", "expectedAtRiskReasons": []},
                "correctedPaper": {
                    "userId": "cp1",
                    "expectedAtRiskReasons": [],
                    "correctedPaperId": "attempt-1",
                },
            },
            parent={"userId": "p1", "phone": "+201000000000", "linkedStudent": "declining"},
        )
        assert payload == {
            "runTag": "tag123",
            "generatedAt": _NOW.isoformat(),
            "teacher": {"userId": "t1"},
            "schoolAdmin": {"userId": "a1"},
            "class": {"classId": "c1", "name": "n", "joinCode": "J1"},
            "students": {
                "declining": {"userId": "d1", "expectedAtRiskReasons": ["declining_trend"]},
                "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
                "control": {"userId": "c1", "expectedAtRiskReasons": []},
                "correctedPaper": {
                    "userId": "cp1",
                    "expectedAtRiskReasons": [],
                    "correctedPaperId": "attempt-1",
                },
            },
            "parent": {"userId": "p1", "phone": "+201000000000", "linkedStudent": "declining"},
        }

    def test_is_json_serializable(self) -> None:
        import json

        payload = build_result_payload(
            run_tag="tag123",
            generated_at=_NOW,
            teacher={"userId": "t1"},
            school_admin={"userId": "a1"},
            class_row={"classId": "c1", "name": "n", "joinCode": "J1"},
            students={"declining": {"userId": "d1", "expectedAtRiskReasons": []}},
            parent={"userId": "p1", "phone": "+201000000000", "linkedStudent": "declining"},
        )
        assert json.loads(json.dumps(payload)) == payload
