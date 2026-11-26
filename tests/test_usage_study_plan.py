"""Spec §2.2 study plans on a seat: the seat pays the first generation per subject per ISO
week when `study_plan` is in scope; a regeneration draws own balance (Task 12). The plan
is a deterministic scheduler (estimate 0-0), so it settles 0 units whoever pays."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.db.study_plan_repo import StudyPlanService
from lemely.web.deps import get_study_plan_service
from lemely.web.usage import get_usage_meter
from tests import test_web_study_plan as _plans
from tests.usage_helpers import (
    NOW,
    enforcing_meter,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

client = _plans.client
pg_sessionmaker = _plans.pg_sessionmaker

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

_URL = "/api/student/study-plan"
_BODY = {"subjectCode": "0625"}


def _wire(client: TestClient, sm: sessionmaker[Session]) -> None:
    seed_catalogue(sm)
    _plans._use_study_plan_service(client, StudyPlanService(sm, now=lambda: NOW))
    cast("FastAPI", client.app).dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)


def test_first_plan_this_week_is_seat_paid_and_the_regeneration_is_not(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.STUDY_PLAN]
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    _plans._auth_as(client, student, Role.student)
    assert client.post(_URL, json=_BODY).status_code == 201
    assert client.post(_URL, json=_BODY).status_code == 201
    first, second = jobs_for(sm, student)
    assert (first.teacher_member_id, second.teacher_member_id) == (member, None)
    assert {first.status, second.status} == {UsageJobStatus.settled}
    assert (first.charged or 0, second.charged or 0) == (0, 0)


def test_without_the_seat_action_the_student_pays(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.MARK_PAPER]
    )
    _plans._auth_as(client, student, Role.student)
    assert client.post(_URL, json=_BODY).status_code == 201
    (job,) = jobs_for(sm, student)
    assert job.teacher_member_id is None


def test_a_seat_for_another_subject_does_not_pay(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.STUDY_PLAN]
    )
    _plans._auth_as(client, student, Role.student)
    assert client.post(_URL, json=_BODY).status_code == 201
    (job,) = jobs_for(sm, student)
    assert job.teacher_member_id is None


def test_a_plan_needs_no_balance_because_it_costs_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student = seed_user(sm)
    _plans._auth_as(client, student, Role.student)
    assert client.post(_URL, json=_BODY).status_code == 201
    (job,) = jobs_for(sm, student)
    assert (job.action, job.status, job.charged or 0) == ("study_plan", UsageJobStatus.settled, 0)


class _ExplodingPlans(StudyPlanService):
    def generate(self, *_args: object, **_kwargs: object) -> object:  # type: ignore[override]
        raise RuntimeError("scheduler blew up")


def test_a_failed_generation_releases_and_charges_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    cast("FastAPI", client.app).dependency_overrides[get_study_plan_service] = lambda: (
        _ExplodingPlans(sm)
    )
    student = seed_user(sm)
    _plans._auth_as(client, student, Role.student)
    with pytest.raises(RuntimeError, match="scheduler blew up"):
        client.post(_URL, json=_BODY)
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged or 0) == (UsageJobStatus.released, 0)


def test_a_non_student_is_refused_before_the_ledger(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    teacher = seed_user(sm, Role.teacher)
    _plans._auth_as(client, teacher, Role.teacher)
    assert client.post(_URL, json=_BODY).status_code == 403
    assert jobs_for(sm, teacher) == []
