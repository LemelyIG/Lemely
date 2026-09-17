"""Enums introduced by the per-question marking detail work (spec 2026-09-17).

``student_evidence_unjudged`` is created here, unused, deliberately: spec D5
says the student self-review spec adds no migration of its own, so every value
it writes must already exist.
"""

from __future__ import annotations

from lemely.db.models.enums import EvidenceVerdict, ReviewReason, RevisionSource


def test_revision_source_members() -> None:
    assert {member.value for member in RevisionSource} == {
        "ai",
        "teacher",
        "student_selfmark",
        "remark",
    }


def test_evidence_verdict_members() -> None:
    assert {member.value for member in EvidenceVerdict} == {
        "accepted",
        "rejected",
        "not_required",
    }


def test_review_reason_gains_student_evidence_unjudged() -> None:
    assert ReviewReason.student_evidence_unjudged.value == "student_evidence_unjudged"


def test_existing_review_reasons_are_untouched() -> None:
    values = {member.value for member in ReviewReason}
    assert {"low_confidence", "plagiarism_flag", "ai_detection_flag"} <= values
