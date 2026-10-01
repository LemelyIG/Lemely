"""`ChildWorker` (#260): a killable, rlimit-bounded child process for scan work.

Every test below runs its target in a real ``spawn``ed child (the targets
live in :mod:`tests.sandbox_targets`), except the one that switches the
sandbox off. Each worker made here is shut down in teardown, and the
``sandboxed`` fixture shuts the two module workers down on both sides of a
test, so no child outlives the test that started it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from lemely.io.scan_limits import ScanRejectedError
from lemely.runtime import sandbox
from lemely.runtime.config import SandboxSettings, Settings
from lemely.runtime.sandbox import (
    EXTRACTION_WORKER,
    INTERACTIVE_WORKER,
    ChildWorker,
    SandboxCrash,
    SandboxError,
    SandboxFailure,
    SandboxMemory,
    SandboxTimeout,
    SandboxUnavailable,
)
from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401

MiB = 2**20
_T = "tests.sandbox_targets"
_RENDER_FIXTURE = Path("tests/fixtures/handwritten-59/0625_w24_qp_42.pdf")

type WorkerFactory = Callable[[int, int], ChildWorker]


@pytest.fixture
def make_worker(sandboxed: None) -> Iterator[WorkerFactory]:  # noqa: F811
    """Fresh workers with the given ``(data, address)`` limits, all shut down after."""
    made: list[ChildWorker] = []

    def make(data_limit: int, address_limit: int) -> ChildWorker:
        worker = ChildWorker(
            "lemely-test-worker", limits=lambda _settings: (data_limit, address_limit)
        )
        made.append(worker)
        return worker

    yield make
    for worker in made:
        worker.shutdown()


@pytest.fixture
def worker(make_worker: WorkerFactory) -> ChildWorker:
    return make_worker(256 * MiB, 512 * MiB)


def _vm_hwm_bytes() -> int:
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    raise AssertionError("no VmHWM in /proc/self/status")


def test_a_target_allocating_past_the_limit_fails_and_the_next_call_succeeds(
    make_worker: WorkerFactory,
) -> None:
    worker = make_worker(256 * MiB, 1024 * MiB)
    first_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)

    with pytest.raises(SandboxFailure) as failure:
        worker.call(
            f"{_T}.lower_data_limit_then",
            96 * MiB,
            f"{_T}.allocate",
            512 * MiB,
            timeout=10,
            result_type=int,
        )

    # A plain bytearray past RLIMIT_DATA is a Python MemoryError (malloc
    # returns NULL; nothing aborts), which the child reports and survives.
    # A C library's allocation failure may arrive otherwise: see the render
    # test below, which accepts any SandboxFailure.
    assert type(failure.value) is SandboxMemory
    assert failure.value.reason == "memory"
    assert worker.last_outcome == "memory"
    assert worker.call(f"{_T}.pid", timeout=5, result_type=int) == first_pid


def test_a_call_waiting_behind_a_busy_worker_is_unavailable_within_its_timeout(
    worker: ChildWorker,
) -> None:
    streamed: list[int] = []
    errors: list[BaseException] = []

    def hold_the_worker() -> None:
        try:
            streamed.extend(worker.stream(f"{_T}.slow_count", 3, 1.0, timeout=10, item_type=int))
        except BaseException as exc:  # reported below, never swallowed
            errors.append(exc)

    holder = threading.Thread(target=hold_the_worker)
    holder.start()
    try:
        time.sleep(0.2)
        started = time.monotonic()
        with pytest.raises(SandboxUnavailable) as refused:
            worker.call(f"{_T}.pid", timeout=0.5, result_type=int)
        waited = time.monotonic() - started
        assert worker.last_outcome == "busy"
    finally:
        holder.join(timeout=20)

    assert str(refused.value) == "busy"
    assert refused.value.reason == "unavailable"
    assert 0.4 <= waited < 1.0
    assert not holder.is_alive()
    assert errors == []
    assert streamed == [0, 1, 2]


def test_a_sleeping_target_is_killed_on_timeout_and_the_pid_changes(worker: ChildWorker) -> None:
    first_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)

    started = time.monotonic()
    with pytest.raises(SandboxTimeout):
        worker.call(f"{_T}.sleep_for", 5.0, timeout=0.3, result_type=type(None))
    assert time.monotonic() - started < 2.0

    assert worker.last_outcome == "timeout"
    assert worker.pid() is None
    second_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)
    assert second_pid != first_pid


def test_a_scan_rejection_arrives_with_its_message_and_reason(worker: ChildWorker) -> None:
    with pytest.raises(ScanRejectedError) as rejected:
        worker.call(f"{_T}.reject", "nope", "page_px", timeout=5, result_type=int)

    assert str(rejected.value) == "nope"
    assert rejected.value.reason == "page_px"
    assert worker.last_outcome == "rejected"


def test_a_rejection_that_cannot_cross_the_pipe_is_a_sandbox_error_and_the_child_lives(
    worker: ChildWorker,
) -> None:
    first_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)

    with pytest.raises(SandboxError) as failed:
        worker.call(f"{_T}.reject_unrebuildable", "nope", timeout=5, result_type=int)

    assert "_KeywordOnlyRejection('nope')" in str(failed.value)
    assert worker.last_outcome == "error"
    assert worker.call(f"{_T}.pid", timeout=5, result_type=int) == first_pid


def test_a_crash_respawns_the_child(worker: ChildWorker) -> None:
    first_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)

    with pytest.raises(SandboxCrash):
        worker.call(f"{_T}.crash", timeout=5, result_type=type(None))

    assert worker.last_outcome == "crash"
    assert worker.pid() is None
    assert worker.call(f"{_T}.pid", timeout=10, result_type=int) != first_pid


def test_a_non_lemely_exception_is_a_sandbox_error_with_the_repr(worker: ChildWorker) -> None:
    with pytest.raises(SandboxError) as failed:
        worker.call(f"{_T}.allocate", -1, timeout=5, result_type=int)

    assert "ValueError" in str(failed.value)
    assert failed.value.reason == "error"
    assert worker.last_outcome == "error"


def test_stream_yields_items_in_order_under_one_deadline(worker: ChildWorker) -> None:
    assert list(worker.stream(f"{_T}.count_up", 5, timeout=5, item_type=int)) == [0, 1, 2, 3, 4]
    assert worker.last_outcome == "ok"


def test_closing_a_stream_early_kills_the_child_and_the_next_call_respawns(
    worker: ChildWorker,
) -> None:
    items = worker.stream(f"{_T}.slow_count", 3, 5.0, timeout=30, item_type=int)
    assert next(items) == 0
    first_pid = worker.pid()
    assert first_pid is not None

    started = time.monotonic()
    items.close()
    assert time.monotonic() - started < 2.0

    assert worker.last_outcome == "interrupted"
    assert worker.pid() is None
    assert worker.call(f"{_T}.pid", timeout=10, result_type=int) != first_pid


@pytest.mark.usefixtures("sandboxed")
def test_the_two_module_workers_are_distinct_processes() -> None:
    try:
        extraction_pid = EXTRACTION_WORKER.call(f"{_T}.pid", timeout=30, result_type=int)
        interactive_pid = INTERACTIVE_WORKER.call(f"{_T}.pid", timeout=30, result_type=int)
    finally:
        EXTRACTION_WORKER.shutdown()
        INTERACTIVE_WORKER.shutdown()

    assert extraction_pid != interactive_pid
    assert os.getpid() not in {extraction_pid, interactive_pid}


def test_disabled_sandbox_runs_the_target_in_process(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=False))

    assert worker.call(f"{_T}.pid", timeout=5, result_type=int) == os.getpid()
    assert worker.pid() is None


def test_the_child_runs_under_both_rlimits(worker: ChildWorker) -> None:
    limits = worker.call(f"{_T}.rlimits", timeout=10, result_type=tuple)

    assert limits == (256 * MiB, 512 * MiB)


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc/self/status")
def test_a_render_out_of_memory_is_a_sandbox_failure_and_the_worker_recovers(
    make_worker: WorkerFactory, record_property: Callable[[str, object], None]
) -> None:
    worker = make_worker(512 * MiB, 1024 * MiB)
    try:
        with open("/proc/self/clear_refs", "w") as clear:
            clear.write("5")
    except OSError:
        pytest.skip("cannot reset this process's VmHWM")
    before = _vm_hwm_bytes()

    with pytest.raises(SandboxFailure) as failure:
        worker.call(
            f"{_T}.lower_data_limit_then",
            48 * MiB,
            "lemely.io.rasterise.rasterise_pdf_to_pages",
            _RENDER_FIXTURE,
            timeout=60,
            result_type=list,
        )
    grown = _vm_hwm_bytes() - before

    # Which subclass depends on where the allocation failed (pdfium's
    # PdfiumError -> SandboxError, a Python MemoryError -> SandboxMemory, an
    # abort -> SandboxCrash); the claim is recovery and a bounded parent.
    assert isinstance(failure.value, SandboxError | SandboxMemory | SandboxCrash)
    record_property("render_failure", f"{type(failure.value).__name__}: {failure.value}")
    assert worker.call(f"{_T}.pid", timeout=30, result_type=int) > 0
    assert grown < 32 * MiB


def test_shutdown_clears_the_start_cool_down(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "_spawn", lambda: False)
    with pytest.raises(SandboxUnavailable):
        worker.call(f"{_T}.pid", timeout=5, result_type=int)
    assert worker.last_outcome == "unavailable"
    monkeypatch.undo()

    # Still inside the 30 s cool-down: refused without trying to start.
    assert worker._start_failed_at is not None
    with pytest.raises(SandboxUnavailable):
        worker.call(f"{_T}.pid", timeout=5, result_type=int)

    worker.shutdown()
    assert worker._start_failed_at is None
    assert worker.call(f"{_T}.pid", timeout=10, result_type=int) != os.getpid()


def test_the_settings_block_round_trips_through_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_SANDBOX__ENABLED", "false")
    monkeypatch.setenv("LEMELY_SANDBOX__EXTRACTION_DATA_LIMIT_BYTES", str(100 * MiB))

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.sandbox.enabled is False
    assert settings.sandbox.extraction_data_limit_bytes == 100 * MiB
    assert settings.sandbox.interactive_data_limit_bytes == 192 * MiB


def test_sandbox_settings_is_read_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []

    def counting_stub() -> Settings:
        calls.append(None)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setattr(sandbox, "load_settings", counting_stub)
    sandbox.sandbox_settings.cache_clear()
    try:
        for _ in range(3):
            assert sandbox.sandbox_settings().enabled is True
    finally:
        sandbox.sandbox_settings.cache_clear()

    assert len(calls) == 1
