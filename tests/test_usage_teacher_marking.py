"""Metering on console marking (phase 04 Task 10): reserve in the request, settle on the pool.

``POST /api/papers/upload`` is metered as ``mark_paper`` and ``POST /api/papers/{id}/regrade``
as ``regrade``, both through :func:`~lemely.web.usage.request_from_team`. The hold is taken in
the handler, while ``actor.member_id`` is known, so the 402 comes back before anything is
stored or submitted to the grading pool. The pool thread opens the cost scope
(``with job.run():``) and settles on success, or releases when the run fails, loses its claim,
finds the paper deleted, or resolves no scheme (billing spec §2.4: failed work costs nothing).
"""

from __future__ import annotations

import functools
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc

from lemely.core.metered_actions import JOB_SLACK, MeteredAction
from lemely.db.models import TeacherPaper
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import UsageGrantBalance, UsageJobStatus
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.teacher_paper_repo import TeacherPaperDeletedError, TeacherPaperRepository
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.db.usage_ledger_repo import UsageLedger
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
from lemely.web.usage import (
    USAGE_UNAVAILABLE_MESSAGE,
    MeteredJob,
    UsageGrantContext,
    UsageMeter,
    UsageRequest,
    UsageUnavailable,
    get_usage_meter,
)
from tests.pdf_fakes import born_digital_text_pdf
from tests.storage_fakes import FakeStorageBackend
from tests.test_grading_binding import _report as _binding_report
from tests.test_teacher_paper_repo import _mark_scheme, _report
from tests.usage_helpers import (
    NOW,
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


class _ThreadPool:
    """Runs each submitted job on a fresh thread, the way ``ThreadPoolExecutor`` does.

    A new ``threading.Thread`` does not inherit the request's context, so a cost scope
    opened in the request (around the submit) would not see the job's costs: the job must
    meter itself on its own thread. ``submit`` joins the thread before returning, so the
    settle is visible when the request returns. With ``hold`` set, submits are queued
    instead, and ``drain`` runs them later, each on its own thread (a job waiting in the
    executor's queue). A job's exception is kept, as a ``Future`` would keep it.
    """

    def __init__(self) -> None:
        self.submitted = 0
        self.hold = False
        self.queued: list[Callable[[], object]] = []
        self.errors: list[BaseException] = []

    def _run_on_a_thread(self, call: Callable[[], object]) -> None:
        def _target() -> None:
            try:
                call()
            except BaseException as exc:
                self.errors.append(exc)

        worker = threading.Thread(target=_target)
        worker.start()
        worker.join()

    def submit(self, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        self.submitted += 1
        call = functools.partial(fn, *args, **kwargs)
        if self.hold:
            self.queued.append(call)
        else:
            self._run_on_a_thread(call)

    def drain(self) -> None:
        queued, self.queued = self.queued, []
        for call in queued:
            self._run_on_a_thread(call)

    def drain_one(self) -> None:
        self._run_on_a_thread(self.queued.pop(0))


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
        pool: _ThreadPool,
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
    pool = _ThreadPool()

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


def _paper(sm: sessionmaker[Session], paper_id: str) -> TeacherPaper:
    with sm() as session:
        row = session.get(TeacherPaper, uuid.UUID(paper_id))
        assert row is not None
        session.expunge(row)
        return row


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
    before = _paper(sm, paper_id)
    assert before.status is UploadStatus.complete
    submitted = console.pool.submitted
    resp = _regrade(console, paper_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"
    assert console.pool.submitted == submitted
    assert [j.action for j in jobs_for(sm, teacher)] == ["mark_paper"]
    # The claim never happened: the row is not stuck in `processing` for the stale window.
    after = _paper(sm, paper_id)
    assert (after.status, after.run_started_at) == (UploadStatus.complete, before.run_started_at)


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


def test_a_binding_gate_hold_fails_the_paper_and_charges_nothing(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _held(_extracted: object) -> None:
        raise grading_service.BindingHeldError(_binding_report("hold"), "before_marking")

    monkeypatch.setattr(grading_service, "ensure_binding_allows_marking", _held)
    _as(console, teacher)
    paper_id = _upload(console).json()["paperId"]
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged, job.debt_created) == (UsageJobStatus.released, 0, 0)
    assert _remaining(sm, grant) == (1000, 0)
    row = _paper(sm, paper_id)
    assert (row.status, row.error) == (
        UploadStatus.failed,
        grading_service.TEACHER_BINDING_HELD_MESSAGE,
    )


def test_a_run_reclaimed_while_queued_is_abandoned_and_the_paper_is_charged_once(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I1: a stale claim reclaimed by a re-run must not mark, or charge, the paper twice."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    _as(console, teacher)
    console.pool.hold = True
    paper_id = _upload(console).json()["paperId"]  # job 1 waits in the pool's queue
    # Nothing writes to a queued row, so after the stale window it reads as a lost run
    # and the console invites a re-run, which reclaims it.
    with sm.begin() as session:
        row = session.get(TeacherPaper, uuid.UUID(paper_id))
        assert row is not None
        row.updated_at = datetime.now(UTC) - timedelta(minutes=20)
    assert _regrade(console, paper_id).status_code == 202  # job 2 queues behind job 1
    graded: list[str] = []

    def _grade(*_a: object, **_k: object) -> object:
        graded.append("grade")
        record_llm_cost(Decimal("0.020"))
        return _report()

    monkeypatch.setattr(grading_service, "grade_paper", _grade)
    console.pool.drain()
    assert console.pool.errors == []
    jobs = jobs_for(sm, teacher)
    assert [(j.action, j.status, j.charged) for j in jobs] == [
        ("mark_paper", UsageJobStatus.released, 0),
        ("regrade", UsageJobStatus.settled, 50),
    ]
    assert graded == ["grade"]
    assert _remaining(sm, grant) == (950, 0)
    assert _paper(sm, paper_id).status is UploadStatus.complete


def test_a_run_reclaimed_mid_run_does_not_save_or_charge(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second token check, before ``finish``: a run superseded while grading discards."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    finished: list[uuid.UUID] = []
    real_finish = TeacherPaperRepository.finish

    def _recording_finish(self: TeacherPaperRepository, pid: uuid.UUID, report: object) -> None:
        finished.append(pid)
        real_finish(self, pid, report)  # type: ignore[arg-type]

    def _grade_then_reclaimed(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.020"))
        with sm.begin() as session:
            # Another request reclaimed the row while this run was grading.
            session.execute(
                sa.update(TeacherPaper)
                .where(TeacherPaper.uploaded_by == teacher)
                .values(run_started_at=datetime.now(UTC) + timedelta(hours=1))
            )
        return _report()

    monkeypatch.setattr(TeacherPaperRepository, "finish", _recording_finish)
    monkeypatch.setattr(grading_service, "grade_paper", _grade_then_reclaimed)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert finished == []
    assert _remaining(sm, grant) == (1000, 0)


def test_a_setup_failure_before_the_run_opens_releases_the_hold(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)

    def _no_thread(*_a: object, **_k: object) -> object:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(teacher_router.bus, "subscribe_queue", _no_thread)
    _as(console, teacher)
    assert _upload(console).status_code == 200
    assert [str(e) for e in console.pool.errors] == ["can't start new thread"]
    (job,) = jobs_for(sm, teacher)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_a_hold_that_expired_while_queued_with_no_balance_left_fails_the_paper_free(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``job.run()`` re-reserves an expired hold on entry; with no balance left it is blocked."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=120)  # exactly one hold's worth
    _as(console, teacher)
    console.pool.hold = True
    first = _upload(console).json()["paperId"]  # queued, holding all 120
    with sm.begin() as session:
        # The sweeper closes the queued job's hold: its deadline passed in the queue.
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(hours=2)) == 1
    second = _upload(console).json()["paperId"]  # the freed 120 now holds paper 2
    calls: list[str] = []

    def _extract(*_a: object, **_k: object) -> list[object]:
        calls.append("extract")
        record_llm_cost(Decimal("0.030"))
        return []

    monkeypatch.setattr(grading_service, "extract_answers", _extract)
    console.pool.drain()
    assert console.pool.errors == []
    assert calls == ["extract"]  # paper 2 only: paper 1 made no model call
    blocked = _paper(sm, first)
    assert (blocked.status, blocked.error) == (
        UploadStatus.failed,
        teacher_router.CREDITS_RAN_OUT_MESSAGE,
    )
    assert _paper(sm, second).status is UploadStatus.complete
    jobs = jobs_for(sm, teacher)
    assert [(j.status, j.charged) for j in jobs] == [
        (UsageJobStatus.expired, 0),
        (UsageJobStatus.settled, 50),
    ]
    assert _remaining(sm, grant) == (70, 0)


def test_a_blocked_run_that_was_superseded_leaves_the_newer_runs_paper_alone(
    console: _Console, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A queued run blocked on entry must not fail a row a re-run has since reclaimed."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=120)
    _as(console, teacher)
    console.pool.hold = True
    paper_id = _upload(console).json()["paperId"]  # job 1 queued, holding all 120
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(hours=2)) == 1
        row = session.get(TeacherPaper, uuid.UUID(paper_id))
        assert row is not None
        row.updated_at = datetime.now(UTC) - timedelta(minutes=20)  # reads as a lost run
    assert _regrade(console, paper_id).status_code == 202  # job 2 reclaims and holds 120
    console.pool.drain_one()  # job 1: blocked on entry, superseded
    between = _paper(sm, paper_id)
    assert (between.status, between.error) == (UploadStatus.processing, None)
    console.pool.drain_one()  # job 2: the run that owns the row
    assert console.pool.errors == []
    row_after = _paper(sm, paper_id)
    assert (row_after.status, row_after.error) == (UploadStatus.complete, None)
    jobs = jobs_for(sm, teacher)
    assert [(j.action, j.status, j.charged) for j in jobs] == [
        ("mark_paper", UsageJobStatus.expired, 0),
        ("regrade", UsageJobStatus.settled, 50),
    ]
    assert _remaining(sm, grant) == (70, 0)


def _ledger_cannot_restart_the_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unavailable(_self: MeteredJob) -> None:
        raise UsageUnavailable

    monkeypatch.setattr(MeteredJob, "_restart_clock", _unavailable)


def test_a_ledger_that_cannot_restart_the_hold_fails_the_paper_plainly_and_free(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``UsageUnavailable`` on entry: the plain sentence (no "Grading failed:"), no model call."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    _as(console, teacher)
    _ledger_cannot_restart_the_hold(monkeypatch)
    calls: list[str] = []

    def _extract(*_a: object, **_k: object) -> list[object]:
        calls.append("extract")
        return []

    monkeypatch.setattr(grading_service, "extract_answers", _extract)
    paper_id = _upload(console).json()["paperId"]
    assert console.pool.errors == []
    assert calls == []
    row = _paper(sm, paper_id)
    assert (row.status, row.error) == (UploadStatus.failed, USAGE_UNAVAILABLE_MESSAGE)
    assert not row.error.startswith("Grading failed")
    assert all(j.charged == 0 for j in jobs_for(sm, teacher))
    assert _remaining(sm, grant)[0] == 1000


def test_a_real_extend_failure_fails_the_paper_plainly_and_releases_the_job(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledger itself fails (nothing forced on ``MeteredJob``): the hold's renewal.

    The paper queues behind the pool, and by the time it runs less than a whole
    ``job_timeout`` is left of the reserved lease. ``UsageLedger.extend`` fails both
    attempts, so ``_restart_clock`` raises ``UsageUnavailable`` itself. The paper fails with
    the plain sentence, no model call is made, and the job ends ``released`` with the
    balance whole.
    """
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    grant = give(sm, teacher, units=1000)
    clock = [NOW]
    meter = UsageMeter(sm, enforce=True, now=lambda: clock[0])
    console.api.app.dependency_overrides[get_usage_meter] = lambda: meter  # type: ignore[attr-defined]
    _as(console, teacher)
    calls: list[str] = []

    def _extract(*_a: object, **_k: object) -> list[object]:
        calls.append("extract")
        return []

    monkeypatch.setattr(grading_service, "extract_answers", _extract)
    console.pool.hold = True
    paper_id = _upload(console).json()["paperId"]  # reserved at NOW, queued
    clock[0] = NOW + JOB_SLACK + timedelta(minutes=1)  # under one job_timeout of lease left
    extends: list[object] = []

    def _ledger_down(*_a: object, **_k: object) -> object:
        extends.append(1)
        raise sa_exc.OperationalError("UPDATE", {}, Exception("ledger down"))

    monkeypatch.setattr(UsageLedger, "extend", _ledger_down)
    console.pool.drain_one()
    assert console.pool.errors == []
    assert len(extends) == 2  # the run's own extend and its one retry
    assert calls == []
    row = _paper(sm, paper_id)
    assert (row.status, row.error) == (UploadStatus.failed, USAGE_UNAVAILABLE_MESSAGE)
    (job,) = jobs_for(sm, teacher)
    assert (job.action, job.status, job.charged) == ("mark_paper", UsageJobStatus.released, 0)
    assert _remaining(sm, grant) == (1000, 0)


def test_an_unavailable_run_that_was_superseded_leaves_the_newer_runs_paper_alone(
    console: _Console,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same superseded-run guard as the credits block: a stale run never fails a re-run's row."""
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=1000)
    _as(console, teacher)
    console.pool.hold = True
    paper_id = _upload(console).json()["paperId"]  # job 1 queued
    with sm.begin() as session:
        row = session.get(TeacherPaper, uuid.UUID(paper_id))
        assert row is not None
        row.updated_at = datetime.now(UTC) - timedelta(minutes=20)  # reads as a lost run
    assert _regrade(console, paper_id).status_code == 202  # job 2 reclaims the row
    real_restart = MeteredJob._restart_clock
    state = {"first": True}

    def _first_run_only(self: MeteredJob) -> None:
        if state["first"]:
            state["first"] = False
            raise UsageUnavailable
        real_restart(self)

    monkeypatch.setattr(MeteredJob, "_restart_clock", _first_run_only)
    console.pool.drain_one()  # job 1: unavailable on entry, superseded
    between = _paper(sm, paper_id)
    assert (between.status, between.error) == (UploadStatus.processing, None)
    console.pool.drain_one()  # job 2 owns the row and completes
    assert console.pool.errors == []
    row_after = _paper(sm, paper_id)
    assert (row_after.status, row_after.error) == (UploadStatus.complete, None)
