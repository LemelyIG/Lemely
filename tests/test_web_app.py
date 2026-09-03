"""Tests for the FastAPI web backend spine (lemely.web).

Covers the health endpoint, the SSE bridge over the event bus (with a fake
publisher — no live Gemini), and one core→DTO conversion round-trip.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
)
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.runtime.events import EventType, bus
from lemely.web import create_app
from lemely.web.routers import meta
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


def test_health_survives_an_unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """A database failure reports gradeBoundariesLoaded=false, not a 500.

    ``gradeBoundariesLoaded`` is computed by reading ``component_thresholds``,
    so the endpoint gained a database dependency it did not have before. A
    health check that 500s when the database is down tells an operator only
    "something is wrong"; the flag names which half is broken.
    """
    monkeypatch.setattr("lemely.web.routers.meta._boundary_read_failing", False)
    monkeypatch.setattr(
        "lemely.web.routers.meta.get_boundary_store",
        lambda: (_ for _ in ()).throw(OperationalError("SELECT 1", {}, Exception("down"))),
    )
    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json()["gradeBoundariesLoaded"] is False


def test_health_survives_a_corrupt_threshold_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-SQLAlchemy failure inside the store must degrade, not 500.

    ``_percentages`` raises ``ValueError`` on a non-positive ``max_mark`` and
    would raise ``TypeError`` on a non-numeric value inside the ``thresholds``
    JSONB. Neither is a ``SQLAlchemyError``, and a corrupt row must not be able
    to take the health endpoint down.
    """
    monkeypatch.setattr("lemely.web.routers.meta._boundary_read_failing", False)
    monkeypatch.setattr(
        "lemely.web.routers.meta.get_boundary_store",
        lambda: (_ for _ in ()).throw(ValueError("max_mark must be positive")),
    )
    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json()["gradeBoundariesLoaded"] is False


def _failing_health_client(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> TestClient:
    monkeypatch.setattr(
        "lemely.web.routers.meta.get_boundary_store",
        lambda: (_ for _ in ()).throw(exc),
    )
    return TestClient(create_app())


def test_health_logs_one_traceback_per_outage_but_a_line_every_poll(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Health is probe traffic, so the traceback must not repeat per poll.

    But the one-line warning must, because `docs/deployment.md` tells an
    operator to look for that line to tell "database unreachable" apart from
    "ingest never ran". Suppressing it entirely would delete the signal the
    docs point at for anyone who starts reading logs mid-outage.
    """
    monkeypatch.setattr("lemely.web.routers.meta._boundary_read_failing", False)
    client = _failing_health_client(monkeypatch, OperationalError("SELECT 1", {}, Exception()))

    with caplog.at_level(logging.WARNING, logger="lemely.web.routers.meta"):
        for _ in range(4):
            assert client.get("/api/health").json()["gradeBoundariesLoaded"] is False

    unreadable = [r for r in caplog.records if "could not read grade boundaries" in r.message]
    assert len(unreadable) == 4, "the discriminating log line must appear on every failing poll"
    with_traceback = [r for r in unreadable if r.exc_info is not None]
    assert len(with_traceback) == 1, "the traceback must be logged once per outage, not per poll"


def test_health_clears_the_failure_flag_when_the_database_answers_but_is_unseeded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An `EmptyGradeBoundaryStoreError` is a *successful* read.

    The database answered; it just has no verified rows. If that path does not
    clear the failure flag, an outage that recovers into a not-yet-ingested
    database leaves the flag stuck `True` -- and a later, genuinely different
    failure is then never logged at all. The operator sees
    `gradeBoundariesLoaded: false` with no log line and, following the docs,
    concludes "ingest never ran" while the database is in fact unreadable.
    """
    monkeypatch.setattr("lemely.web.routers.meta._boundary_read_failing", True)
    empty = EmptyGradeBoundaryStoreError("no verified rows")
    assert _failing_health_client(monkeypatch, empty).get("/api/health").status_code == 200
    assert meta._boundary_read_failing is False

    # ...so a different failure arriving afterwards is still reported *with its
    # traceback*. Asserting merely that the line appears would not discriminate:
    # the per-poll warning emits that same line whether or not the flag is stuck.
    # Only the `exc_info` record is unique to the transition.
    with caplog.at_level(logging.WARNING, logger="lemely.web.routers.meta"):
        client = _failing_health_client(monkeypatch, ValueError("corrupt max_mark"))
        assert client.get("/api/health").json()["gradeBoundariesLoaded"] is False

    assert [r for r in caplog.records if r.exc_info is not None]


def test_health_failure_log_names_the_exception_in_the_message_itself(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exception type must survive into the rendered message.

    `lemely.runtime.logging` bridges stdlib records into structlog with
    `structlog.get_logger(...).log(levelno, record.getMessage())` -- it drops
    `record.exc_info` entirely. So a bare `logger.exception` reaches a deployed
    log as a bare string, and an operator cannot tell an `OperationalError`
    (database unreachable) from a `TypeError` (corrupt thresholds JSONB). That
    distinction is the whole reason this record exists, so the repr goes in the
    message. Asserting on `caplog`'s `exc_info` would bypass the bridge and
    pass while production stayed empty; this asserts on the rendered text.
    """
    monkeypatch.setattr("lemely.web.routers.meta._boundary_read_failing", False)
    client = _failing_health_client(monkeypatch, ValueError("corrupt max_mark"))

    with caplog.at_level(logging.WARNING, logger="lemely.web.routers.meta"):
        client.get("/api/health")

    rendered = [r.getMessage() for r in caplog.records]
    assert any("ValueError" in m and "corrupt max_mark" in m for m in rendered), rendered


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
