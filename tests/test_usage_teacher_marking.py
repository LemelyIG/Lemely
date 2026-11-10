"""Metering on console marking (phase 04 Task 10): reserve in the request, settle on the pool.

``POST /api/papers/upload`` is metered as ``mark_paper`` and ``POST /api/papers/{id}/regrade``
as ``regrade``, both through :func:`~lemely.web.usage.request_from_team`. The hold is taken in
the handler, while ``actor.member_id`` is known, so the 402 comes back before anything is
stored or submitted to the grading pool. The pool thread opens the cost scope
(``with job.run():``) and settles on success, or releases when the run fails, loses its claim,
finds the paper deleted, or resolves no scheme (billing spec §2.4: failed work costs nothing).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import UsageGrantBalance, UsageJobStatus
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.teacher_paper_repo import TeacherPaperDeletedError, TeacherPaperRepository
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.io.gemini import GeminiClient
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_gemini_client,
    get_history_store,
    get_scheme_corpus_repo,
    get_storage_backend,
    get_teacher_paper_repo,
    get_teacher_team_store,
)
from lemely.web.routers import student as student_router
from lemely.web.routers import teacher as teacher_router
from lemely.web.services import grading as grading_service
from lemely.web.usage import UsageGrantContext, UsageMeter, UsageRequest, get_usage_meter
from tests.pdf_fakes import born_digital_text_pdf
from tests.storage_fakes import FakeStorageBackend
from tests.test_teacher_paper_repo import _mark_scheme, _report
from tests.usage_helpers import (
    assistant,
    enforcing_meter,
    give,
    jobs_for,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

_SCAN = born_digital_text_pdf(pages=1)


class _InlinePool:
    """Runs a submitted job at once, so the settle is visible when the request returns."""

    def __init__(self) -> None:
        self.submitted = 0

    def submit(self, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        self.submitted += 1
        fn(*args, **kwargs)


class _CountingStorage(FakeStorageBackend):
    """Counts uploads, so a 402 test can prove nothing reached the bucket."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads = 0

    def upload(self, bucket: str, object_path: str, data: bytes, content_type: str | None) -> None:
        self.uploads += 1
        super().upload(bucket, object_path, data, content_type)


class _Console:
    def __init__(
        self,
        api: TestClient,
        repo: TeacherPaperRepository,
        storage: _CountingStorage,
        pool: _InlinePool,
    ) -> None:
        self.api = api
        self.repo = repo
        self.storage = storage
        self.pool = pool


@pytest.fixture
def console(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[_Console]:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    repo = TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))
    storage = _CountingStorage()
    pool = _InlinePool()

    def _extract(*_a: object, **_k: object) -> list[object]:
        record_llm_cost(Decimal("0.030"))
        return []

    def _grade(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.020"))
        return _report()

    monkeypatch.setattr(teacher_router, "_grading_pool", pool)
    monkeypatch.setattr(teacher_router, "_detection_available", lambda _settings: False)
    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: _mark_scheme())
    monkeypatch.setattr(grading_service, "extract_answers", _extract)
    monkeypatch.setattr(grading_service, "ensure_binding_allows_marking", lambda _x: None)
    monkeypatch.setattr(grading_service, "grade_paper", _grade)

    app = create_app()
    app.dependency_overrides[get_teacher_paper_repo] = lambda: repo
    app.dependency_overrides[get_storage_backend] = lambda: storage
    app.dependency_overrides[get_history_store] = lambda: MagicMock()
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: SchemeCorpusRepository(sm)
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    yield _Console(TestClient(app), repo, storage, pool)
    app.dependency_overrides.clear()


def _as(c: _Console, user: uuid.UUID) -> None:
    c.api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(user), role="teacher"
    )


def _upload(c: _Console, acting_for: uuid.UUID | None = None) -> Response:
    headers = {ACTING_TEACHER_HEADER: str(acting_for)} if acting_for is not None else {}
    return c.api.post(
        "/api/papers/upload",
        files={"scan": ("scan.pdf", _SCAN, "application/pdf")},
        headers=headers,
    )


def _regrade(c: _Console, paper_id: str, acting_for: uuid.UUID | None = None) -> Response:
    headers = {ACTING_TEACHER_HEADER: str(acting_for)} if acting_for is not None else {}
    return c.api.post(f"/api/papers/{paper_id}/regrade", headers=headers)


def _remaining(sm: sessionmaker[Session], grant_id: uuid.UUID) -> tuple[int, int]:
    with sm() as session:
        balance = session.get(UsageGrantBalance, grant_id)
        assert balance is not None
        return balance.remaining, balance.held


def _nothing_stored(c: _Console, owner: uuid.UUID) -> None:
    assert c.repo.list_visible(viewer_id=owner, viewer_role=Role.teacher) == []
    assert c.storage.uploads == 0
    assert c.pool.submitted == 0


# --- upload ---------------------------------------------------------------------------------


def test_upload_without_balance_is_402_before_anything_is_stored_or_submitted(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    _as(console, teacher)
    resp = _upload(console)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "no_active_plan"
    _nothing_stored(console, teacher)
    assert jobs_for(migrated_sessionmaker, teacher) == []


def test_upload_charges_the_marking_cost(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.action, job.status, job.charged) == ("mark_paper", UsageJobStatus.settled, 50)
    assert _remaining(sm, grant) == (950, 0)


def test_an_assistants_upload_and_regrade_bill_the_lead_never_the_assistant(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """R4: team work under the acting-teacher header is charged to the lead teacher."""
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    _as(console, helper)
    # The lead has nothing; the helper's own 1000 never counts.
    blocked = _upload(console, acting_for=lead)
    assert blocked.status_code == 402
    assert blocked.json()["reason"] == "no_active_plan"
    _nothing_stored(console, lead)
    lead_grant = give(sm, lead, units=1000)
    paper_id = _upload(console, acting_for=lead).json()["paperId"]
    assert _regrade(console, paper_id, acting_for=lead).status_code == 202
    jobs = jobs_for(sm, helper)
    assert [(j.action, j.teacher_member_id, j.status, j.charged) for j in jobs] == [
        ("mark_paper", member, UsageJobStatus.settled, 50),
        ("regrade", member, UsageJobStatus.settled, 50),
    ]
    assert _remaining(sm, own) == (1000, 0)
    assert _remaining(sm, lead_grant) == (900, 0)
    assert jobs_for(sm, lead) == []


def test_an_assistant_over_its_cap_is_402_and_the_lead_pays_nothing(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    lead_grant = give(sm, lead, units=5000)
    assistant(sm, teacher=lead, member=helper, cap_units=30)  # below the 120-unit top of range
    _as(console, helper)
    resp = _upload(console, acting_for=lead)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"
    _nothing_stored(console, lead)
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, lead_grant) == (5000, 0)


def test_a_removed_assistant_is_403_and_never_falls_back_to_its_own_balance(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=1000)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    _as(console, helper)
    resp = _upload(console, acting_for=lead)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    _nothing_stored(console, lead)
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, own) == (1000, 0)


class _RemovesTheAssistantFirst(UsageMeter):
    """Removes the assistant row between the team guard and the meter's chain load."""

    def __init__(self, sm: sessionmaker[Session], member: uuid.UUID) -> None:
        base = enforcing_meter(sm)
        super().__init__(sm, enforce=True, now=base.now)
        self._member = member

    def authorize(self, request: UsageRequest) -> UsageGrantContext:
        with self.sessionmaker.begin() as session:
            row = session.get(TeacherMember, self._member)
            assert row is not None
            row.status = TeacherMemberStatus.removed
        return super().authorize(request)


def test_an_assistant_removed_after_the_guard_is_the_meters_403_and_nothing_is_stored(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=1000)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    console.api.app.dependency_overrides[get_usage_meter] = (  # type: ignore[attr-defined]
        lambda: _RemovesTheAssistantFirst(sm, member)
    )
    _as(console, helper)
    resp = _upload(console, acting_for=lead)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    _nothing_stored(console, lead)
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, own) == (1000, 0)


def test_a_storage_failure_after_the_hold_releases_it(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _down(*_a: object, **_k: object) -> None:
        raise OSError("bucket unreachable")

    monkeypatch.setattr(console.storage, "upload", _down)
    _as(console, teacher)
    with pytest.raises(OSError, match="bucket unreachable"):
        _upload(console)
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)
    assert console.pool.submitted == 0


# --- regrade --------------------------------------------------------------------------------


def test_regrade_as_oneself_is_metered_as_regrade_on_ones_own_chain(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=1000)
    _as(console, teacher)
    paper_id = _upload(console).json()["paperId"]
    assert _regrade(console, paper_id).status_code == 202
    jobs = jobs_for(sm, teacher)
    assert [(j.action, j.teacher_member_id, j.status, j.charged) for j in jobs] == [
        ("mark_paper", None, UsageJobStatus.settled, 50),
        ("regrade", None, UsageJobStatus.settled, 50),
    ]
    assert jobs[1].action == MeteredAction.REGRADE.value


def test_regrade_without_balance_is_402_before_the_run_is_claimed(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=120)
    _as(console, teacher)
    paper_id = _upload(console).json()["paperId"]  # spends 50 of 120; 70 < 120 is left
    submitted = console.pool.submitted
    resp = _regrade(console, paper_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"
    assert console.pool.submitted == submitted
    assert [j.action for j in jobs_for(sm, teacher)] == ["mark_paper"]


def test_a_lost_claim_releases_the_hold(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    _as(console, teacher)
    paper_id = _upload(console).json()["paperId"]
    monkeypatch.setattr(TeacherPaperRepository, "claim_run", lambda _self, _pid: False)
    assert _regrade(console, paper_id).status_code == 202
    last = jobs_for(sm, teacher)[-1]
    assert (last.action, last.status, last.charged) == ("regrade", UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (950, 0)


# --- the pool thread ------------------------------------------------------------------------


def test_a_failed_run_is_released_and_charges_nothing(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _broken(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.010"))
        raise RuntimeError("model down")

    monkeypatch.setattr(grading_service, "grade_paper", _broken)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged, job.debt_created) == (UsageJobStatus.released, 0, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_a_paper_deleted_mid_run_is_released(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _deleted(_self: TeacherPaperRepository, paper_id: uuid.UUID, *_a: object) -> None:
        raise TeacherPaperDeletedError(paper_id)

    monkeypatch.setattr(TeacherPaperRepository, "finish", _deleted)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_a_run_that_resolves_no_scheme_is_released(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _no_scheme(*_a: object, **_k: object) -> None:
        record_llm_cost(Decimal("0.005"))
        return None

    monkeypatch.setattr(student_router, "resolve_mark_scheme", _no_scheme)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_a_paper_missing_when_the_run_starts_is_released(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    monkeypatch.setattr(TeacherPaperRepository, "get", lambda _self, _pid: None)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_a_pool_that_refuses_the_submit_releases_the_regrade_hold(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    _as(console, teacher)
    paper_id = _upload(console).json()["paperId"]

    def _shut(*_a: object, **_k: object) -> None:
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(console.pool, "submit", _shut)
    with pytest.raises(RuntimeError, match="after shutdown"):
        _regrade(console, paper_id)
    last = jobs_for(sm, teacher)[-1]
    assert (last.action, last.status, last.charged) == ("regrade", UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (950, 0)
