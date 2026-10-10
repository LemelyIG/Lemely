"""Bus events that must stay on the server are never streamed to a browser.

``lemely.web.sse.bus_event_stream`` relays a run's bus events to the client as SSE
frames. The binding gate's result carries the whole binding report (check ids, counts,
question ids, the gate's sentences): it is for the server's log and its subscribers,
not for the student whose paper it is about.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from lemely.runtime.events import EventType, bus
from lemely.web import sse
from lemely.web.sse import bus_event_stream

_REPORT = {
    "binder": "label",
    "checks": [
        {
            "id": "G5",
            "passed": False,
            "scope": "paper",
            "question_ids": ["3c", "4a"],
            "detail": "5 of 43 questions could not be lined up with a label on the page.",
        }
    ],
    "verdict": "hold",
    "retried": True,
    "model": "gemini-3.8-flash",
}


def _frames(publish_between: bool) -> list[str]:
    app = FastAPI()

    def _run() -> None:
        bus.publish(EventType.EXTRACTION_PROGRESS, question_id="1a", index=1, total=2)
        if publish_between:
            bus.publish(
                EventType.BINDING_GATE_RESULT,
                binder="label",
                gate="enforce",
                verdict="hold",
                retried=True,
                failed_checks=["G5"],
                unbound=3,
                unaligned=5,
                inferred_numbers=[],
                drops={},
                model="gemini-3.8-flash",
                second_read=True,
                first_read_failed_checks=[],
                report=_REPORT,
            )
        bus.publish(EventType.MARKING_PROGRESS, question_id="1a", index=1, total=2)
        bus.publish_done()

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        return StreamingResponse(
            bus_event_stream(_run, poll_seconds=0.02), media_type="text/event-stream"
        )

    with TestClient(app).stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    return [frame for frame in text.split("\n\n") if frame.strip()]


def test_the_binding_gate_result_never_reaches_the_client() -> None:
    frames = _frames(publish_between=True)
    # The two progress frames and the sentinel arrive exactly as without the event.
    assert frames == _frames(publish_between=False)
    assert len(frames) == 3 and frames[-1] == "data: [DONE]"
    assert '"type": "extraction_progress"' in frames[0]
    assert '"type": "marking_progress"' in frames[1]
    wire = "\n".join(frames)
    for leaked in ("binding_gate_result", "G5", "3c", "could not be lined up", "verdict"):
        assert leaked not in wire


def test_the_binding_gate_result_is_the_only_event_kept_back_today() -> None:
    assert frozenset({EventType.BINDING_GATE_RESULT}) == sse.SERVER_ONLY_EVENTS
