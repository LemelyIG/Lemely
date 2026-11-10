"""Metering on the SSE self-mark route, ``POST /api/student/correct`` (billing phase 04 Task 9).

The subject is read off the scan inside the job, so the request only pre-checks every
chain the subject could turn out to need against the *top* of the ``mark_paper``
estimate (a short balance is a 402 before the stream starts), and the worker reserves
once ``job.bind_subject`` knows the subject. A block after that point ends the stream
with an ``error`` frame carrying ``code: "usage_blocked"``. Every model call here is a
stub that records a fixed cost; no Gemini call is made.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.attempts import Attempt, Upload
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.models.usage import GrantKind, UsageDebt, UsageJob, UsageJobStatus
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.runtime.events import EventType, bus
from lemely.web import sse
from lemely.web.routers import student
from lemely.web.usage import USAGE_BLOCKED_MESSAGE, MeteredJob, UsageBlocked, get_usage_meter
from tests import test_student_correct as _student_correct
from tests.usage_helpers import (
    NOW,
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

# Fixtures are re-exported by attribute (see tests/test_student_self_review_web.py for why).
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

#: The ``mark_paper`` estimate seeded by the catalogue (flat, ``input_kind = "none"``).
ESTIMATE = [40, 120]
#: The scan-metadata call's stub cost, the extraction call's and the paid mark-scheme
#: resolve's: 10, 40 and 20 units.
DETECT_USD = Decimal("0.010")
EXTRACT_USD = Decimal("0.040")
RESOLVE_USD = Decimal("0.020")
_WAIT = 15.0


class _Calls:
    """What the stubbed pipeline did, so a 402 can be shown to start no work."""

    def __init__(self) -> None:
        self.detected = 0
        self.extracted = 0


@pytest.fixture
def calls(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> _Calls:
    """Enforce metering on the route and stub the two paid calls with fixed costs."""
    api, _, _ = client
    app = cast("FastAPI", api.app)
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(pg_sessionmaker)
    seed_catalogue(pg_sessionmaker)
    seen = _Calls()

    class _Detector:
        def __init__(self, _client: object) -> None: ...

        def __call__(self, _scan_path: object) -> SimpleNamespace:
            seen.detected += 1
            record_llm_cost(DETECT_USD)
            return SimpleNamespace(subject_code="0580")

    extracted = _student_correct._extracted()

    def _extract(*_a: object, **_k: object) -> object:
        seen.extracted += 1
        record_llm_cost(EXTRACT_USD)
        return extracted

    monkeypatch.setattr(student, "llm_key_configured", lambda *_a, **_k: True)
    monkeypatch.setattr(student, "ScanMetadataExtractor", _Detector)
    monkeypatch.setattr(student, "extract_answers", _extract)
    return seen


@pytest.fixture
def api(client: tuple[TestClient, str, StudentUploadRepository], calls: _Calls) -> TestClient:
    del calls
    return client[0]


@pytest.fixture
def student_id(client: tuple[TestClient, str, StudentUploadRepository]) -> uuid.UUID:
    return uuid.UUID(client[1])


def _upload(api: TestClient) -> str:
    up = api.post(
        "/api/student/uploads", files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")}
    )
    assert up.status_code == 200, up.text
    return str(up.json()["paperId"])


def _errors(text: str) -> list[dict[str, object]]:
    return [f for f in _student_correct._frames(text) if f["type"] == EventType.ERROR.value]


def _available(sm: sessionmaker[Session], payer: Payer) -> int:
    with sm() as session:
        return UsageLedger(session).available([payer], now=NOW)


def _own(student_id: uuid.UUID, scope: GrantScope) -> Payer:
    return Payer(owner_user_id=student_id, scope=scope)


def _upload_status(sm: sessionmaker[Session], paper_id: str) -> UploadStatus:
    with sm() as session:
        row = session.get(Upload, uuid.UUID(paper_id))
        assert row is not None
        return row.status


def _attempts(sm: sessionmaker[Session], student_id: uuid.UUID) -> int:
    with sm() as session:
        return len(session.scalars(select(Attempt).where(Attempt.user_id == student_id)).all())


def _terminal_job(sm: sessionmaker[Session], student_id: uuid.UUID) -> UsageJob:
    """The student's one job, once the worker has settled or released it."""
    deadline = time.monotonic() + _WAIT
    while time.monotonic() < deadline:
        jobs = jobs_for(sm, student_id)
        if jobs and jobs[0].status is not UsageJobStatus.open:
            (job,) = jobs
            return job
        time.sleep(0.05)
    raise AssertionError(f"the job never left 'open': {jobs_for(sm, student_id)}")


# --- 402 before the stream: the pre-check covers the top of the range -----------------


def test_no_balance_is_a_402_before_any_stream(
    api: TestClient, student_id: uuid.UUID, calls: _Calls, pg_sessionmaker: sessionmaker[Session]
) -> None:
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 402
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "no_active_plan",
        "estimate": ESTIMATE,
    }
    assert jobs_for(pg_sessionmaker, student_id) == []
    assert (calls.detected, calls.extracted) == (0, 0)


def test_a_balance_below_the_top_of_the_estimate_is_a_402_up_front(
    api: TestClient, student_id: uuid.UUID, calls: _Calls, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """100 units would cover a typical paper (50) but not the top of 40-120, so the
    stream never starts: no mid-stream block, and the platform pays for no scan read."""
    give(pg_sessionmaker, student_id, units=100)
    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 402
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "insufficient_credits",
        "estimate": ESTIMATE,
    }
    assert (calls.detected, calls.extracted) == (0, 0)
    assert jobs_for(pg_sessionmaker, student_id) == []
    assert _upload_status(pg_sessionmaker, paper_id) is UploadStatus.pending
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 100


def test_outstanding_debt_is_a_402_up_front(
    api: TestClient, student_id: uuid.UUID, calls: _Calls, pg_sessionmaker: sessionmaker[Session]
) -> None:
    give(pg_sessionmaker, student_id, units=1000)
    with pg_sessionmaker.begin() as session:
        session.add(UsageDebt(owner_user_id=student_id, job_id=None, units=10, outstanding=10))
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 402
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "outstanding_debt",
        "estimate": ESTIMATE,
    }
    assert (calls.detected, calls.extracted) == (0, 0)
    assert jobs_for(pg_sessionmaker, student_id) == []


def test_a_wrong_role_is_403_before_any_ledger_read(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The role guard runs before the meter: a teacher never reaches ``authorize``."""
    from lemely.web.deps import AuthContext, get_auth_context

    api, _, _ = client
    app = cast("FastAPI", api.app)
    paper_id = _upload(api)
    teacher = seed_user(pg_sessionmaker, Role.teacher)

    class _Exploding:
        def authorize(self, *_a: object, **_k: object) -> None:
            raise AssertionError("the meter ran before the role guard")

    app.dependency_overrides[get_usage_meter] = _Exploding
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(teacher), role="teacher"
    )
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 403


# --- Settled in the worker -------------------------------------------------------------


def test_own_credits_pay_the_actual_cost(
    api: TestClient, student_id: uuid.UUID, pg_sessionmaker: sessionmaker[Session]
) -> None:
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.action == MeteredAction.MARK_PAPER.value
    assert job.charged == 50
    assert job.teacher_member_id is None
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 950


def test_a_non_seated_student_pays_their_allowance_then_their_credits(
    api: TestClient, student_id: uuid.UUID, pg_sessionmaker: sessionmaker[Session]
) -> None:
    give(
        pg_sessionmaker,
        student_id,
        units=30,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=NOW.replace(month=12, day=1),
    )
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert job.teacher_member_id is None
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.ALLOWANCE)) == 0
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 980


def test_a_maths_scan_is_paid_by_the_maths_seat(
    api: TestClient, student_id: uuid.UUID, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    maths, physics = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    maths_seat = seat(
        sm, teacher=maths, student=student_id, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    physics_seat = seat(
        sm,
        teacher=physics,
        student=student_id,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student_id, member_id=maths_seat, units=500)
    seat_grant(sm, student=student_id, member_id=physics_seat, units=500)
    give(sm, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(sm, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.teacher_member_id == maths_seat
    assert job.charged == 50
    seat_payer = Payer(
        owner_user_id=student_id, scope=GrantScope.SEAT, teacher_member_id=maths_seat
    )
    assert _available(sm, seat_payer) == 450
    # The student's own credits and the other subject's seat are untouched.
    assert _available(sm, _own(student_id, GrantScope.CREDITS)) == 1000
    other = Payer(owner_user_id=student_id, scope=GrantScope.SEAT, teacher_member_id=physics_seat)
    assert _available(sm, other) == 500


# --- Blocked after the subject is bound: an error frame, nothing charged ----------------


def test_a_detected_subject_nobody_pays_for_ends_the_stream_with_usage_blocked(
    api: TestClient, student_id: uuid.UUID, calls: _Calls, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    physics = seed_user(sm, Role.teacher)
    physics_seat = seat(
        sm,
        teacher=physics,
        student=student_id,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student_id, member_id=physics_seat, units=500)
    paper_id = _upload(api)
    with capture_logs() as logs:
        resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200  # the physics seat could have paid, so the stream started
    errors = _errors(resp.text)
    assert len(errors) == 1
    assert errors[0]["code"] == "usage_blocked"
    assert errors[0]["reason"] == "no_active_plan"
    assert errors[0]["message"] == USAGE_BLOCKED_MESSAGE
    assert '"phase": "complete"' not in resp.text
    assert "[DONE]" in resp.text
    # Nothing held, nothing charged; only the scan read ran, and its cost is logged.
    assert jobs_for(sm, student_id) == []
    assert (calls.detected, calls.extracted) == (1, 0)
    seat_payer = Payer(
        owner_user_id=student_id, scope=GrantScope.SEAT, teacher_member_id=physics_seat
    )
    assert _available(sm, seat_payer) == 500
    unmetered = [e for e in logs if e["event"] == "usage_unmetered_cost"]
    assert [(e["cost_usd"], e["exempt"]) for e in unmetered] == [("0.010", False)]
    assert _upload_status(sm, paper_id) is UploadStatus.failed
    assert _attempts(sm, student_id) == 0


def test_a_seat_on_the_subject_that_does_not_cover_marking_is_out_of_seat_scope(
    api: TestClient, student_id: uuid.UUID, calls: _Calls, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The maths seat covers only self-review, so a maths scan is out of its scope.

    The subject is unknown when the request arrives, so this reason can only be found
    once the scan is read: the stream starts (the physics seat could have paid) and
    ends with ``out_of_seat_scope``.
    """
    sm = pg_sessionmaker
    maths, physics = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    maths_seat = seat(
        sm,
        teacher=maths,
        student=student_id,
        subjects=["0580"],
        actions=[MeteredAction.SELF_REVIEW],
    )
    physics_seat = seat(
        sm,
        teacher=physics,
        student=student_id,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student_id, member_id=maths_seat, units=500)
    seat_grant(sm, student=student_id, member_id=physics_seat, units=500)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    (error,) = _errors(resp.text)
    assert (error["code"], error["reason"]) == ("usage_blocked", "out_of_seat_scope")
    assert jobs_for(sm, student_id) == []
    assert calls.extracted == 0


# --- Failure paths release ---------------------------------------------------------------


def test_a_pipeline_failure_releases_and_charges_nothing(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: object, **_k: object) -> object:
        record_llm_cost(EXTRACT_USD)
        raise RuntimeError("extraction fell over")

    monkeypatch.setattr(student, "extract_answers", _boom)
    give(pg_sessionmaker, student_id, units=1000)
    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200
    (error,) = _errors(resp.text)
    assert "code" not in error
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.released
    assert (job.charged, job.debt_created) == (0, 0)
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 1000
    assert _upload_status(pg_sessionmaker, paper_id) is UploadStatus.failed


def test_no_mark_scheme_abandons_the_job_and_charges_nothing(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scan read cost money, but no paper was marked: a failure without a raise."""
    monkeypatch.setattr(student, "resolve_mark_scheme", lambda *_a, **_k: None)
    give(pg_sessionmaker, student_id, units=1000)
    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200
    assert "No mark scheme available" in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.released
    assert job.charged == 0
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 1000
    assert _upload_status(pg_sessionmaker, paper_id) is UploadStatus.failed


# --- Client disconnect: the run goes on, and still settles or releases ----------------


@pytest.fixture
def disconnect(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Make the client hang up after the first frame (as ``tests/test_run_cap.py`` does).

    The returned event is set once the stream is closed, so a stub can hold the run
    until the client has gone.
    """
    gone = threading.Event()
    real = sse.bus_event_stream

    async def _hang_up(run: Callable[[], Any], **kwargs: Any) -> AsyncIterator[str]:
        stream = real(run, **kwargs)
        first = await asyncio.wait_for(anext(stream), _WAIT)
        await stream.aclose()  # the client is gone
        gone.set()
        yield first

    monkeypatch.setattr(sse, "bus_event_stream", _hang_up)
    return gone


def _held_extract(gone: threading.Event, *, fail: bool) -> Callable[..., object]:
    extracted = _student_correct._extracted()

    def _extract(*_a: object, **_k: object) -> object:
        bus.publish(EventType.WARNING, message="extracting")
        assert gone.wait(_WAIT), "the client never hung up"
        record_llm_cost(EXTRACT_USD)
        if fail:
            raise RuntimeError("extraction fell over after the client left")
        return extracted

    return _extract


def test_a_disconnect_then_a_pipeline_failure_releases(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    disconnect: threading.Event,
) -> None:
    monkeypatch.setattr(student, "extract_answers", _held_extract(disconnect, fail=True))
    give(pg_sessionmaker, student_id, units=1000)
    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200
    assert "extracting" in resp.text
    job = _terminal_job(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.released
    assert job.charged == 0
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 1000


def test_a_disconnect_never_leaves_the_hold_open_and_a_finished_paper_is_charged(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    disconnect: threading.Event,
) -> None:
    """Closing the page ends the stream, not the run (``lemely.web.sse``): the paper is
    still marked and stored for the student to reload, so the work it did is charged."""
    monkeypatch.setattr(student, "extract_answers", _held_extract(disconnect, fail=False))
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' not in resp.text
    job = _terminal_job(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert _attempts(pg_sessionmaker, student_id) == 1


# --- No detected subject: the student's own balance pays, and the hold still happens ----
#
# `job.bind_subject(None)` is what reserves when detection is switched off or fails. If the
# route skipped the bind there (``if metadata is not None: job.bind_subject(...)``), the job
# would stay pending, nothing would be held, and the paper would be marked for free.


class _FailingDetector:
    """A scan-metadata extractor whose model call raises before it records any cost."""

    def __init__(self, _client: object) -> None: ...

    def __call__(self, _scan_path: object) -> SimpleNamespace:
        raise RuntimeError("the metadata read fell over")


def test_a_failed_detection_is_paid_from_the_students_own_balance(
    api: TestClient,
    student_id: uuid.UUID,
    calls: _Calls,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(student, "ScanMetadataExtractor", _FailingDetector)
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert "Could not detect scan metadata" in resp.text
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.teacher_member_id is None
    assert job.charged == 40  # the extraction only: the failed read cost nothing
    assert calls.extracted == 1
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 960


def test_detection_switched_off_is_paid_from_the_students_own_balance(
    api: TestClient,
    student_id: uuid.UUID,
    calls: _Calls,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        student,
        "llm_key_configured",
        lambda _settings, purpose, *_a, **_k: purpose != "scan_metadata",
    )
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.teacher_member_id is None
    assert job.charged == 40
    assert (calls.detected, calls.extracted) == (0, 1)
    assert _available(pg_sessionmaker, _own(student_id, GrantScope.CREDITS)) == 960


def test_a_seat_only_student_whose_detection_fails_is_blocked_in_stream_and_charged_nothing(
    api: TestClient,
    student_id: uuid.UUID,
    calls: _Calls,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The physics seat could pay, so the stream starts; without a subject only the
    student's own (empty) balance can, so the stream ends with ``usage_blocked``."""
    sm = pg_sessionmaker
    monkeypatch.setattr(student, "ScanMetadataExtractor", _FailingDetector)
    physics = seed_user(sm, Role.teacher)
    physics_seat = seat(
        sm,
        teacher=physics,
        student=student_id,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student_id, member_id=physics_seat, units=500)
    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200
    (error,) = _errors(resp.text)
    assert (error["code"], error["reason"]) == ("usage_blocked", "no_active_plan")
    assert error["message"] == USAGE_BLOCKED_MESSAGE
    assert '"phase": "complete"' not in resp.text
    assert jobs_for(sm, student_id) == []
    assert calls.extracted == 0
    seat_payer = Payer(
        owner_user_id=student_id, scope=GrantScope.SEAT, teacher_member_id=physics_seat
    )
    assert _available(sm, seat_payer) == 500
    assert _upload_status(sm, paper_id) is UploadStatus.failed
    assert _attempts(sm, student_id) == 0


# --- The hold comes before any paid mark-scheme resolve ---------------------------------


def test_the_hold_is_placed_before_the_paid_mark_scheme_resolve(
    api: TestClient,
    student_id: uuid.UUID,
    calls: _Calls,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheme parse that falls back to Gemini is a paid call. A stream the subject's
    chain cannot pay for must end at the bind, before that call, so the platform only
    absorbs the scan read; bound after the resolve it would absorb the parse too."""
    sm = pg_sessionmaker
    resolved: list[object] = []
    real = student.resolve_mark_scheme

    def _paid_resolve(*args: object, **kwargs: object) -> object:
        resolved.append(args)
        record_llm_cost(RESOLVE_USD)
        return real(*args, **kwargs)

    monkeypatch.setattr(student, "resolve_mark_scheme", _paid_resolve)
    physics = seed_user(sm, Role.teacher)
    physics_seat = seat(
        sm,
        teacher=physics,
        student=student_id,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student_id, member_id=physics_seat, units=500)
    with capture_logs() as logs:
        resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    (error,) = _errors(resp.text)
    assert error["code"] == "usage_blocked"
    assert resolved == []
    assert (calls.detected, calls.extracted) == (1, 0)
    unmetered = [e for e in logs if e["event"] == "usage_unmetered_cost"]
    assert [e["cost_usd"] for e in unmetered] == ["0.010"]


def test_a_paid_mark_scheme_resolve_runs_inside_the_job_and_is_charged(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = student.resolve_mark_scheme

    def _paid_resolve(*args: object, **kwargs: object) -> object:
        record_llm_cost(RESOLVE_USD)
        return real(*args, **kwargs)

    monkeypatch.setattr(student, "resolve_mark_scheme", _paid_resolve)
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 70  # scan read 10 + scheme parse 20 + extraction 40


# --- Two concurrent streams cannot overdraw one balance ---------------------------------


def test_two_concurrent_streams_on_150_credits_settle_one_and_block_one(
    api: TestClient,
    student_id: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both requests pass the up-front check (150 covers the top, 120, once), then race
    to hold. The locked reserve lets one through (30 left) and refuses the other.

    Deterministic: the detector holds both workers until both are past the up-front
    check, and the winner's extraction waits until the loser has been refused, so
    the winner cannot settle (and free its hold) before the loser tries to bind.
    """
    sm = pg_sessionmaker
    both_authorized = threading.Barrier(2, timeout=_WAIT)
    refused = threading.Event()

    class _Detector:
        def __init__(self, _client: object) -> None: ...

        def __call__(self, _scan_path: object) -> SimpleNamespace:
            both_authorized.wait()
            record_llm_cost(DETECT_USD)
            return SimpleNamespace(subject_code="0580")

    real_bind = MeteredJob.bind_subject

    def _bind(self: MeteredJob, subject: str | None) -> None:
        try:
            real_bind(self, subject)
        except UsageBlocked:
            refused.set()
            raise

    extracted = _student_correct._extracted()

    def _extract(*_a: object, **_k: object) -> object:
        assert refused.wait(_WAIT), "the second stream was never refused"
        record_llm_cost(EXTRACT_USD)
        return extracted

    monkeypatch.setattr(student, "ScanMetadataExtractor", _Detector)
    monkeypatch.setattr(MeteredJob, "bind_subject", _bind)
    monkeypatch.setattr(student, "extract_answers", _extract)
    give(sm, student_id, units=150)
    papers = [_upload(api), _upload(api)]
    bodies: list[str] = []

    def _stream(paper_id: str) -> None:
        resp = api.post("/api/student/correct", json={"paperId": paper_id})
        assert resp.status_code == 200
        bodies.append(resp.text)

    with capture_logs() as logs:
        threads = [threading.Thread(target=_stream, args=(p,)) for p in papers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(_WAIT * 2)
    assert not any(t.is_alive() for t in threads)
    assert len(bodies) == 2
    completed = [b for b in bodies if '"phase": "complete"' in b]
    blocked = [b for b in bodies if "usage_blocked" in b]
    assert (len(completed), len(blocked)) == (1, 1)
    assert completed[0] is not blocked[0]
    (error,) = _errors(blocked[0])
    assert (error["code"], error["reason"]) == ("usage_blocked", "insufficient_credits")
    # One job, settled at its actual cost; no overdraw, no debt.
    (job,) = jobs_for(sm, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert _available(sm, _own(student_id, GrantScope.CREDITS)) == 100
    with sm() as session:
        assert (
            session.scalars(select(UsageDebt).where(UsageDebt.owner_user_id == student_id)).all()
            == []
        )
    # The loser's scan read was paid by the platform and says so in the log.
    unmetered = [e for e in logs if e["event"] == "usage_unmetered_cost"]
    assert [(e["cost_usd"], e["exempt"]) for e in unmetered] == [("0.010", False)]
