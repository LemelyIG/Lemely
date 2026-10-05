"""One marking run at a time per process (``lemely.io.run_cap``; #260, #271).

Owner decision, 2026-10-05: keep the 2 GiB instance and let one run at a time
hold a scan's rendered pages in the web process. These tests drive the real
:class:`~lemely.io.answer_extraction.GeminiAnswerExtractor` with Gemini mocked
(``tests.gemini_fakes``) and the render replaced by a recording fake, so no
render worker is started. The page-holding section is observed from the
inside: it opens when the (fake) render returns pages, and closes at
``normalize_extracted_answers``, the extractor's last step before it lets
them go.
"""

from __future__ import annotations

import asyncio
import contextvars
import io
import json
import tempfile
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswers
from lemely.io import answer_extraction, run_cap
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.events import EventType, bus, current_run_id
from lemely.web.sse import bus_event_stream
from tests.test_answer_extraction import _client_with_response, _minimal_mcq_mark_scheme

#: Bound on every wait in this file, so a regression fails instead of hanging.
_WAIT = 10.0


def _page() -> RasterisedPage:
    buffer = io.BytesIO()
    Image.new("L", (100, 140), color=255).save(buffer, "PNG")
    return RasterisedPage(index=0, width=100, height=140, png_bytes=buffer.getvalue())


@dataclass
class _Sections:
    """What the page-holding sections did, recorded from inside them."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    active: int = 0
    peak: int = 0
    entered: list[str] = field(default_factory=list)
    #: Set when a run first holds its pages.
    first_entered: threading.Event = field(default_factory=threading.Event)
    #: Set by a second run: when it queues for the slot, or when it holds
    #: pages while another run still does.
    second_arrived: threading.Event = field(default_factory=threading.Event)
    #: A run holding its pages waits for this, when a test sets ``hold``.
    release: threading.Event = field(default_factory=threading.Event)
    hold: bool = False
    #: Raised from inside the section, after it has opened.
    fail_with: BaseException | None = None


@pytest.fixture
def sections(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Sections]:
    """A fresh run slot, a recording render and a recording section end."""
    monkeypatch.setattr(run_cap, "_slots", threading.BoundedSemaphore(run_cap.MAX_CONCURRENT_RUNS))
    state = _Sections()

    def fake_render(scan_path: Path) -> list[RasterisedPage]:
        with state.lock:
            state.active += 1
            state.peak = max(state.peak, state.active)
            state.entered.append(scan_path.stem)
            if state.active > 1:
                state.second_arrived.set()
        state.first_entered.set()
        # Something a client's stream sees while this run holds its pages.
        bus.publish(EventType.WARNING, message=f"holding {scan_path.stem}")
        if len(state.entered) == 1:
            # The first run keeps its pages until a second run has arrived:
            # queued for the slot, or (no cap) holding pages beside it.
            state.second_arrived.wait(_WAIT)
            if state.hold:
                state.release.wait(_WAIT)
        if state.fail_with is not None:
            failure, state.fail_with = state.fail_with, None
            _close()
            raise failure
        return [_page()]

    def _close() -> None:
        with state.lock:
            state.active -= 1

    real_normalize = answer_extraction.normalize_extracted_answers

    def recording_normalize(result: ExtractedAnswers, manifest_ids: list[str]) -> ExtractedAnswers:
        _close()
        return real_normalize(result, manifest_ids)

    def on_queued(**_payload: object) -> None:
        state.second_arrived.set()

    monkeypatch.setattr(answer_extraction, "rasterise_scan_to_pages", fake_render)
    monkeypatch.setattr(answer_extraction, "normalize_extracted_answers", recording_normalize)
    bus.subscribe(EventType.EXTRACTION_QUEUED, on_queued)
    try:
        yield state
    finally:
        bus.unsubscribe(EventType.EXTRACTION_QUEUED, on_queued)
        state.release.set()
        state.second_arrived.set()


@dataclass
class _Run:
    """One extraction on its own thread, under its own run id."""

    name: str
    tmp: Path
    result: ExtractedAnswers | None = None
    error: BaseException | None = None
    thread: threading.Thread | None = None

    def start(self) -> _Run:
        extractor, scheme = _extractor(self.tmp), _minimal_mcq_mark_scheme()
        scan = self.tmp / f"{self.name}.pdf"

        def work() -> None:
            current_run_id.set(self.name)
            try:
                self.result = extractor(scan, scheme)
            except BaseException as exc:
                self.error = exc

        self.thread = threading.Thread(
            target=contextvars.copy_context().run, args=(work,), daemon=True
        )
        self.thread.start()
        return self

    def join(self) -> None:
        assert self.thread is not None
        self.thread.join(_WAIT)
        assert not self.thread.is_alive(), f"run {self.name} never finished"
        assert self.error is None, repr(self.error)


def _extractor(tmp: Path) -> GeminiAnswerExtractor:
    return GeminiAnswerExtractor(_client_with_response(str(tmp), {"answers": []}))


def _scheme() -> MarkScheme:
    return _minimal_mcq_mark_scheme()


@pytest.fixture
def tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _drain(q: Any) -> list[tuple[EventType, dict[str, Any]]]:
    events = []
    while not q.empty():
        event = q.get_nowait()
        if event is not None:
            events.append((event.type, event.payload))
    return events


def test_two_concurrent_runs_hold_their_pages_one_after_the_other(
    sections: _Sections, tmp: Path
) -> None:
    """The second run arrives while the first holds its pages, and waits: the
    sections never overlap, and both papers come back."""
    first_queue = bus.subscribe_queue("first")
    second_queue = bus.subscribe_queue("second")
    try:
        first = _Run("first", tmp).start()
        assert sections.first_entered.wait(_WAIT)
        second = _Run("second", tmp).start()
        first.join()
        second.join()
    finally:
        bus.unsubscribe_queue(first_queue)
        bus.unsubscribe_queue(second_queue)

    assert sections.peak == 1, "two runs held their pages at once"
    assert sections.entered == ["first", "second"]
    assert first.result is not None and second.result is not None
    queued = [p for t, p in _drain(second_queue) if t is EventType.EXTRACTION_QUEUED]
    assert queued == [{"message": run_cap.RUN_QUEUED_MESSAGE}]
    assert not [p for t, p in _drain(first_queue) if t is EventType.EXTRACTION_QUEUED]


def test_a_free_slot_is_taken_without_a_queued_status(sections: _Sections, tmp: Path) -> None:
    sections.second_arrived.set()  # nobody else is coming
    seen: list[dict[str, object]] = []

    def spy(**payload: object) -> None:
        seen.append(payload)

    bus.subscribe(EventType.EXTRACTION_QUEUED, spy)
    try:
        _extractor(tmp)(tmp / "alone.pdf", _scheme())
    finally:
        bus.unsubscribe(EventType.EXTRACTION_QUEUED, spy)
    assert seen == []


def _wait_for_free_slot() -> None:
    """Wait (bounded) for the run in flight to give the slot back."""
    assert run_cap._slots.acquire(timeout=_WAIT), "the slot was never released"
    run_cap._slots.release()


def _assert_slot_is_free(tmp: Path) -> None:
    """A new run gets the slot at once: it finishes, and never queues."""
    seen: list[dict[str, object]] = []

    def spy(**payload: object) -> None:
        seen.append(payload)

    bus.subscribe(EventType.EXTRACTION_QUEUED, spy)
    try:
        after = _Run("after", tmp).start()
        after.join()
    finally:
        bus.unsubscribe(EventType.EXTRACTION_QUEUED, spy)
    assert after.result is not None
    assert seen == [], "the slot was still held"


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("render blew up"), KeyboardInterrupt(), SystemExit(1)],
    ids=["exception", "keyboard-interrupt", "system-exit"],
)
def test_the_slot_is_released_when_the_run_raises(
    sections: _Sections, tmp: Path, failure: BaseException
) -> None:
    sections.second_arrived.set()
    sections.fail_with = failure

    with pytest.raises(type(failure)):
        _extractor(tmp)(tmp / "failing.pdf", _scheme())

    _assert_slot_is_free(tmp)


def test_a_run_waiting_behind_a_failing_run_starts_when_it_fails(
    sections: _Sections, tmp: Path
) -> None:
    """The queue never fails a paper: the waiting run goes ahead."""
    sections.fail_with = RuntimeError("the first paper's render failed")
    first = _Run("first", tmp).start()
    assert sections.first_entered.wait(_WAIT)
    second = _Run("second", tmp).start()

    assert first.thread is not None
    first.thread.join(_WAIT)
    assert isinstance(first.error, RuntimeError)
    second.join()
    assert second.result is not None
    assert sections.peak == 1


def test_the_slot_is_released_when_the_awaiting_task_is_cancelled(
    sections: _Sections, tmp: Path
) -> None:
    """A thread cannot be cancelled: a run whose awaiting task is cancelled
    goes on to the end, and gives the slot back there."""
    sections.second_arrived.set()
    sections.hold = True
    extractor, scheme = _extractor(tmp), _scheme()
    # Not the loop's default executor, which ``asyncio.run`` would wait for.
    executor = ThreadPoolExecutor(max_workers=1)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(
            loop.run_in_executor(executor, extractor, tmp / "cancelled.pdf", scheme)
        )
        assert await asyncio.to_thread(sections.first_entered.wait, _WAIT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
        assert sections.active == 1, "the abandoned run should still hold its pages"
        sections.release.set()
        _wait_for_free_slot()
    finally:
        executor.shutdown(wait=True)
    assert sections.active == 0
    _assert_slot_is_free(tmp)


def test_the_slot_is_released_after_the_client_disconnects(sections: _Sections, tmp: Path) -> None:
    """A student who closes the page ends the SSE stream, not the run
    (``lemely.web.sse``): the run finishes and gives the slot back."""
    sections.second_arrived.set()
    sections.hold = True
    extractor, scheme = _extractor(tmp), _scheme()

    def run() -> None:
        try:
            extractor(tmp / "disconnected.pdf", scheme)
        finally:
            bus.publish_done()

    async def scenario() -> str:
        stream = bus_event_stream(run, run_id="student:disconnected")
        first_frame = await asyncio.wait_for(anext(stream), _WAIT)
        await stream.aclose()  # the client is gone
        return first_frame

    first_frame = asyncio.run(scenario())
    assert "holding disconnected" in first_frame
    assert sections.active == 1, "the run should go on after the client has gone"
    sections.release.set()
    _wait_for_free_slot()
    assert sections.active == 0
    _assert_slot_is_free(tmp)


def test_a_waiting_student_stream_says_it_is_queued(sections: _Sections, tmp: Path) -> None:
    """The progress channel: a student's SSE stream gets an
    ``extraction_queued`` frame, carrying the message the progress view
    shows, while their paper waits; then the run goes ahead."""
    sections.hold = True
    first = _Run("first", tmp).start()
    assert sections.first_entered.wait(_WAIT)
    extractor, scheme = _extractor(tmp), _scheme()

    def run() -> None:
        try:
            extractor(tmp / "waiting.pdf", scheme)
        finally:
            bus.publish_done()

    async def scenario() -> list[dict[str, Any]]:
        frames = []
        async for frame in bus_event_stream(run, run_id="student:waiting"):
            body = frame.removeprefix("data: ").strip()
            if body == "[DONE]":
                break
            payload = json.loads(body)
            frames.append(payload)
            if payload["type"] == EventType.EXTRACTION_QUEUED.value:
                sections.release.set()  # now let the run ahead finish
        return frames

    frames = asyncio.run(asyncio.wait_for(scenario(), _WAIT))
    first.join()

    types = [f["type"] for f in frames]
    assert types[0] == "extraction_queued", types
    assert frames[0]["message"] == run_cap.RUN_QUEUED_MESSAGE
    assert {"type": "warning", "message": "holding waiting"} in frames  # it went ahead
    assert sections.peak == 1


def test_the_cap_is_one_run() -> None:
    """Owner decision, 2026-10-05; the 2 GiB budget counts one run
    (``tests/test_sandbox.py::test_the_default_limits_fit_the_accepted_worst_case``)."""
    assert run_cap.MAX_CONCURRENT_RUNS == 1


def test_a_forked_child_starts_with_a_free_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slot a parent's run held is not the child's to wait for."""
    held = threading.BoundedSemaphore(1)
    held.acquire()
    monkeypatch.setattr(run_cap, "_slots", held)
    run_cap._forget_after_fork()
    assert run_cap._slots is not held
    assert run_cap._slots.acquire(blocking=False)
    run_cap._slots.release()
