"""Tests for the FastAPI web backend spine (lemely.web).

Covers the health endpoint, the SSE bridge over the event bus (with a fake
publisher — no live Gemini), and one core→DTO conversion round-trip.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
)
from lemely.runtime.events import EventType, bus
from lemely.web import create_app
from lemely.web.schemas import correction_to_dto, question_to_dto
from lemely.web.sse import bus_event_stream


def test_health_returns_ok() -> None:
    """GET /api/health returns 200 with the expected DTO shape."""
    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "apiKeyConfigured" in body
    assert isinstance(body["apiKeyConfigured"], bool)


def test_stub_routers_are_mounted() -> None:
    """The teacher and student stub routers are included; unknown /api paths 404."""
    client = TestClient(create_app())
    # meta.health is the only concrete route so far; the stub routers add none
    # yet, so an unmapped /api path resolves to 404 rather than a routing error.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404


def _fake_publisher() -> None:
    """Publish two events then signal end-of-stream — stands in for a real pipeline."""
    try:
        bus.publish(
            EventType.EXTRACTION_PROGRESS,
            question_id="1a",
            confidence=0.91,
        )
        bus.publish(
            EventType.MARKING_PROGRESS,
            question_id="1a",
            marker_source="deterministic",
            confidence=1.0,
        )
    finally:
        bus.publish_done()


def test_sse_stream_ends_with_done() -> None:
    """The SSE bridge streams event frames and terminates with a [DONE] frame."""
    app = FastAPI()

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        return StreamingResponse(
            bus_event_stream(_fake_publisher, poll_seconds=0.02),
            media_type="text/event-stream",
        )

    client = TestClient(app)
    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    frames = [f for f in text.split("\n\n") if f.strip()]
    # Every frame is a well-formed SSE `data:` line.
    assert all(f.startswith("data:") for f in frames)
    # The two published events plus the terminal sentinel.
    assert frames[-1] == "data: [DONE]"
    payload_frames = [f for f in frames if f != "data: [DONE]"]
    assert len(payload_frames) == 2
    assert '"type": "extraction_progress"' in payload_frames[0]
    assert '"question_id": "1a"' in payload_frames[0]
    assert '"type": "marking_progress"' in payload_frames[1]


def test_two_concurrent_streams_are_isolated() -> None:
    """Two runs at once: each stream sees only its frames and ends only with its own sentinel."""
    app = FastAPI()

    def _publisher(tag: str, delay: float):
        def run() -> None:
            try:
                time.sleep(delay)
                bus.publish(
                    EventType.MARKING_PROGRESS,
                    question_id=tag,
                    marker_source="deterministic",
                    confidence=1.0,
                )
            finally:
                bus.publish_done()

        return run

    @app.get("/s/{tag}")
    async def stream(tag: str) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        delay = 0.05 if tag == "fast" else 0.4
        return StreamingResponse(
            bus_event_stream(_publisher(tag, delay), poll_seconds=0.02, run_id=tag),
            media_type="text/event-stream",
        )

    client = TestClient(app)
    with ThreadPoolExecutor(2) as pool:
        fast, slow = pool.map(lambda t: client.get(f"/s/{t}").text, ["fast", "slow"])

    assert '"question_id": "fast"' in fast and '"slow"' not in fast
    assert '"question_id": "slow"' in slow and '"fast"' not in slow
    assert fast.count("[DONE]") == 1 and slow.count("[DONE]") == 1
    # `_format_frame` never puts the scoping id on the wire — the wire contract
    # is unchanged even though delivery is now scoped underneath it.
    assert "run_id" not in fast
    assert "run_id" not in slow


def test_correction_to_dto_round_trip() -> None:
    """A core CorrectionResult converts to the camelCase GradeResult DTO."""
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[
            CorrectedQuestion(
                question_id="1a",
                awarded_marks=2,
                maximum_marks=3,
                confidence=ConfidenceBand.HIGH,
                confidence_score=0.95,
                needs_teacher_review=False,
                marker_source="ai",
                feedback="Good working shown.",
                matched_point_ids=["mp1", "mp2"],
            ),
        ],
    )

    dto = correction_to_dto(correction)

    assert dto.awardedMarks == 2
    assert dto.maxMarks == 3
    assert dto.needsTeacherReview is False
    assert len(dto.questions) == 1

    q = dto.questions[0]
    assert q.questionId == "1a"
    assert q.awardedMarks == 2
    assert q.maxMarks == 3
    assert q.markerSource == "ai"
    assert q.confidence == 0.95
    assert q.feedback == "Good working shown."
    assert q.matchedPointIds == ["mp1", "mp2"]
    # Advisory integrity signals default to unflagged.
    assert q.plagiarismFlagged is False
    assert q.aiDetectionFlagged is False

    # camelCase keys survive JSON serialisation for the frontend contract.
    dumped = dto.model_dump()
    assert "awardedMarks" in dumped
    assert "needsTeacherReview" in dumped


def test_question_to_dto_surfaces_integrity_flags() -> None:
    """Plagiarism/AI-detection advisory flags round-trip into the DTO's camelCase fields."""
    question = CorrectedQuestion(
        question_id="2",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.99,
        needs_teacher_review=True,
        marker_source="deterministic",
        review_reason="plagiarism (score 0.95) | ai_detection (score 0.90)",
        plagiarism_flagged=True,
        ai_detection_flagged=True,
    )

    dto = question_to_dto(question)

    assert dto.plagiarismFlagged is True
    assert dto.aiDetectionFlagged is True
    assert dto.reviewReason == "plagiarism (score 0.95) | ai_detection (score 0.90)"
    dumped = dto.model_dump()
    assert dumped["plagiarismFlagged"] is True
    assert dumped["aiDetectionFlagged"] is True


def test_question_to_dto_surfaces_topic() -> None:
    """`CorrectedQuestion.topic` round-trips onto `QuestionResultDTO.topic` (P2.7 step 5)."""
    question = CorrectedQuestion(
        question_id="3",
        awarded_marks=1,
        maximum_marks=2,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.9,
        needs_teacher_review=False,
        marker_source="deterministic",
        topic="Forces and motion",
    )

    dto = question_to_dto(question)

    assert dto.topic == "Forces and motion"
    assert dto.model_dump()["topic"] == "Forces and motion"

    # A question with no detected topic surfaces as None, not a fabricated string.
    untopic = question_to_dto(
        CorrectedQuestion(
            question_id="4",
            awarded_marks=0,
            maximum_marks=1,
            confidence=ConfidenceBand.LOW,
            confidence_score=0.1,
            needs_teacher_review=True,
            marker_source="missing",
        )
    )
    assert untopic.topic is None


def test_health_reports_storage_backend_without_touching_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DS12: the health route names the backend and bucket from settings only,
    and is structurally forbidden from ever building a storage backend to do
    it — Task 19's deploy smoke test relies on health never making a network
    call. Guarded two ways because each covers a hole the other leaves:

    - ``app.dependency_overrides`` (this repo's own convention for this exact
      dependency — see ``tests/test_web_student.py``): FastAPI resolves
      ``Depends(...)`` by the callable's identity at *request* time, so this
      catches a regression shaped like ``student.py``'s own
      ``Annotated[StorageBackend, Depends(get_storage_backend)]`` — even
      though that ``Depends(...)`` would have captured the callable back when
      ``lemely.web.routers.meta`` was first imported, long before this test
      runs. A same-module-attribute patch (e.g.
      ``monkeypatch.setattr("lemely.web.deps.get_storage_backend", ...)``)
      does NOT catch this shape: proven by a live regression injection during
      review (see the task report).
    - Patching both backend constructors (``GcsStorageBackend.__init__``,
      ``LocalFileStorageBackend.__init__``) to raise: catches a direct call
      through a from-imported name, which dependency_overrides cannot see
      since that path never goes through FastAPI's ``Depends`` resolution.
    """
    monkeypatch.setenv("LEMELY_STORAGE__BACKEND", "gcs")
    monkeypatch.setenv("LEMELY_STORAGE__BUCKET", "proj-uploads-staging")
    from lemely.web.deps import get_storage_backend, reset_singletons

    reset_singletons()  # a warm cache would return an instance without constructing one

    def _dependency_must_not_be_called() -> None:
        raise AssertionError("health must not build a storage backend")

    def _ctor_must_not_be_called(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("health must not construct a storage backend")

    monkeypatch.setattr(
        "lemely.io.storage_gcs.GcsStorageBackend.__init__", _ctor_must_not_be_called
    )
    monkeypatch.setattr(
        "lemely.io.storage_local.LocalFileStorageBackend.__init__", _ctor_must_not_be_called
    )

    app = create_app()
    app.dependency_overrides[get_storage_backend] = _dependency_must_not_be_called
    body = TestClient(app).get("/api/health").json()
    app.dependency_overrides.clear()
    monkeypatch.undo()  # restore the real constructors so cache_clear() below works

    assert body["storage"] == {"backend": "gcs", "bucket": "proj-uploads-staging"}
    reset_singletons()


def test_stream_ends_when_the_worker_dies_without_a_sentinel() -> None:
    """The liveness guard: a run that never publishes its sentinel must not hang.

    Scoping made this reachable. `EventBus.publish_done` delivers only to
    queues whose scope matches the *current* run id, so a sentinel published
    from the wrong context — or never published at all, because `run` died
    before its `finally` — leaves this scoped queue waiting on something that
    will never arrive. The drain loop treats an empty poll as "keep waiting",
    so without the guard it spins for the life of the connection, pinning a
    Cloud Run instance that this plan is about to make one of only three.

    Bounded by a daemon thread and an explicit join rather than left to run:
    if the guard regresses, this fails in ten seconds instead of hanging the
    suite, and the leaked thread cannot block interpreter exit.
    """
    app = FastAPI()

    @app.get("/orphan")
    async def stream() -> StreamingResponse:
        def run() -> None:
            bus.publish(EventType.WARNING, message="orphan-event")
            # Deliberately no `bus.publish_done()` — the failure under test.

        return StreamingResponse(
            bus_event_stream(run, poll_seconds=0.02, run_id="orphan-run"),
            media_type="text/event-stream",
        )

    client = TestClient(app)
    body: list[str] = []
    reader = threading.Thread(target=lambda: body.append(client.get("/orphan").text), daemon=True)
    reader.start()
    reader.join(timeout=10.0)

    assert not reader.is_alive(), (
        "the stream never ended: bus_event_stream kept polling after its worker exited "
        "without publishing a sentinel, which is exactly the hang the liveness guard exists "
        "to prevent"
    )
    # The event published before the worker exited is still delivered, not
    # dropped by the shortcut out of the loop.
    assert '"message": "orphan-event"' in body[0]
    assert body[0].count("[DONE]") == 1
