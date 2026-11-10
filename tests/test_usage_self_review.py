"""Metering on self-review (Task 12): only evidence can reach the judge, so only evidence
is metered; the subject and inputs come from the caller's own attempt, never another user's."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.db.self_review_repo import SelfReviewService
from lemely.db.usage_context_repo import self_review_target
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import get_usage_meter
from tests import test_student_correct as _student_correct
from tests import test_student_self_review_web as _web
from tests.usage_helpers import (
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

client = _student_correct.client
corpus_repo = _student_correct.corpus_repo
gemini_client = _student_correct.gemini_client
pg_sessionmaker = _student_correct.pg_sessionmaker
settings = _student_correct.settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.upload_repo import StudentUploadRepository


@pytest.fixture
def wired(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, str, str, str]:
    api, student_id = _web._wire(client, pg_sessionmaker)
    cast("FastAPI", api.app).dependency_overrides[get_usage_meter] = lambda: enforcing_meter(
        pg_sessionmaker
    )
    seed_catalogue(pg_sessionmaker)
    original = SelfReviewService.submit

    def _costly(self: SelfReviewService, *args: object, **kwargs: object) -> object:
        # The judge's spend is recorded before the service may still refuse the pass, so a
        # refused pass proves that a failed job charges nothing whatever it spent.
        record_llm_cost(Decimal("0.003"))
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SelfReviewService, "submit", _costly)
    attempt_id, qr_id = _web._seed_attempt(pg_sessionmaker, student_id)
    return api, student_id, attempt_id, qr_id


def test_target_reads_the_attempts_subject_and_point_count(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    _, student_id, attempt_id, qr_id = wired
    with pg_sessionmaker() as session:
        target = self_review_target(
            session, student_id=student_id, attempt_id=attempt_id, question_result_id=qr_id
        )
        foreign = self_review_target(
            session, student_id=str(uuid.uuid4()), attempt_id=attempt_id, question_result_id=qr_id
        )
    assert target is not None
    assert target.subject_code == "0580"
    assert target.input_count == 3
    assert foreign is None


def test_evidence_without_balance_is_402(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 402
    # base 1-2 + 3 marks x 0-1 = 1-5
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [1, 5]}
    assert jobs_for(pg_sessionmaker, uuid.UUID(student_id)) == []


def test_evidence_with_balance_settles(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 200, resp.text
    (job,) = jobs_for(pg_sessionmaker, uuid.UUID(student_id))
    assert (job.action, job.status, job.charged) == ("self_review", UsageJobStatus.settled, 3)


def test_no_evidence_is_never_metered(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    # No balance either: a pass without evidence cannot reach the judge, so it is free.
    assert api.post(_web._path(attempt_id, qr_id), json=_web._full_pass()).status_code == 200
    assert jobs_for(pg_sessionmaker, uuid.UUID(student_id)) == []


def test_blank_evidence_is_not_evidence(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="   "))
    assert resp.status_code == 200, resp.text
    assert jobs_for(pg_sessionmaker, uuid.UUID(student_id)) == []


def test_one_point_with_evidence_meters_the_whole_pass(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    body = _web._full_pass()
    cast("list[dict[str, object]]", body["points"])[1]["evidence"] = "I wrote 12 N"
    assert api.post(_web._path(attempt_id, qr_id), json=body).status_code == 402
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    assert api.post(_web._path(attempt_id, qr_id), json=body).status_code == 200
    (job,) = jobs_for(pg_sessionmaker, uuid.UUID(student_id))
    assert job.status is UsageJobStatus.settled


def test_a_refused_pass_charges_nothing(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    partial = {"points": [{"markPointId": "p1", "earned": True, "evidence": "I wrote 12 N"}]}
    assert api.post(_web._path(attempt_id, qr_id), json=partial).status_code == 422
    (job,) = jobs_for(pg_sessionmaker, uuid.UUID(student_id))
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)


def test_a_second_pass_is_409_and_costs_nothing(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    body = _web._full_pass(evidence="I wrote 12 N")
    assert api.post(_web._path(attempt_id, qr_id), json=body).status_code == 200
    assert api.post(_web._path(attempt_id, qr_id), json=body).status_code == 409
    first, second = jobs_for(pg_sessionmaker, uuid.UUID(student_id))
    assert (first.status, first.charged) == (UsageJobStatus.settled, 3)
    assert (second.status, second.charged) == (UsageJobStatus.released, 0)


def test_someone_elses_question_is_still_a_404_and_unmetered(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, _ = wired
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    resp = api.post(_web._path(attempt_id, str(uuid.uuid4())), json=_web._full_pass(evidence="x"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "No such question"}
    assert jobs_for(pg_sessionmaker, uuid.UUID(student_id)) == []


def test_another_students_attempt_is_a_404_with_no_job_and_no_charge(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    """IDOR: the subject and the point count come from the caller's own attempt only."""
    api, student_id, _, _ = wired
    sm = pg_sessionmaker
    victim = seed_user(sm)
    victim_attempt, victim_qr = _web._seed_attempt(sm, str(victim))
    give(sm, uuid.UUID(student_id), units=100)
    resp = api.post(
        _web._path(victim_attempt, victim_qr), json=_web._full_pass(evidence="I wrote 12 N")
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "No such question"}
    assert jobs_for(sm, uuid.UUID(student_id)) == []
    assert jobs_for(sm, victim) == []


def test_a_seat_covering_the_attempts_subject_pays(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    sm = pg_sessionmaker
    student = uuid.UUID(student_id)
    member = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.SELF_REVIEW],
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 200, resp.text
    (job,) = jobs_for(sm, student)
    assert (job.teacher_member_id, job.status, job.charged) == (member, UsageJobStatus.settled, 3)


def test_a_seat_for_another_subject_does_not_pay(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    sm = pg_sessionmaker
    student = uuid.UUID(student_id)
    member = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.SELF_REVIEW],
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 402
    assert resp.json()["reason"] == "no_active_plan"


def test_a_seat_without_the_action_in_scope_is_out_of_seat_scope(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    sm = pg_sessionmaker
    seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=uuid.UUID(student_id),
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 402
    assert resp.json()["reason"] == "out_of_seat_scope"
