"""`ChildWorker` (#260): a killable, rlimit-bounded child process for scan work.

Every test below runs its target in a real ``spawn``ed child (the targets
live in :mod:`tests.sandbox_targets`), except the one that switches the
sandbox off. Each worker made here is shut down in teardown, and the
``sandboxed`` fixture shuts the two module workers down on both sides of a
test, so no child outlives the test that started it.
"""

from __future__ import annotations

import gc
import logging
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_the_child_runs_under_both_rlimits_and_dumps_no_core(worker: ChildWorker) -> None:
    limits = worker.call(f"{_T}.rlimits", timeout=10, result_type=tuple)

    assert limits == (256 * MiB, 512 * MiB, 0)
    # The child's ready message reports what it actually applied.
    assert worker.applied_limits == (256 * MiB, 512 * MiB, 0)


_CLAMPED_LIMIT_SCRIPT = textwrap.dedent(
    """
    import logging, resource
    resource.setrlimit(resource.RLIMIT_DATA, (300 * 2**20, 300 * 2**20))
    from lemely.runtime import sandbox
    from lemely.runtime.config import SandboxSettings
    sandbox.sandbox_settings = lambda: SandboxSettings()
    messages = []
    class Keep(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())
    logger = logging.getLogger("lemely.runtime.sandbox")
    logger.addHandler(Keep())
    logger.setLevel(logging.WARNING)
    worker = sandbox.ChildWorker("clamped", limits=lambda s: (512 * 2**20, 1024 * 2**20))
    if __name__ == "__main__":
        try:
            worker.call("tests.sandbox_targets.pid", timeout=30, result_type=int)
            print(worker.applied_limits)
            print(messages)
        finally:
            worker.shutdown()
    """
)


@pytest.mark.skipif(sys.platform != "linux", reason="lowers a hard rlimit in a subprocess")
def test_a_limit_the_child_could_not_apply_is_warned_about_in_the_parent() -> None:
    """The parent's hard RLIMIT_DATA (300 MiB) caps the child's: asking for
    512 MiB leaves the child at 300 MiB, and the parent says so."""
    proc = subprocess.run(  # noqa: S603 -- our own interpreter and a fixed script
        [sys.executable, "-c", _CLAMPED_LIMIT_SCRIPT],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )

    assert proc.returncode == 0, proc.stderr
    applied, messages = proc.stdout.strip().splitlines()[-2:]
    assert applied == str((300 * MiB, 1024 * MiB, 0))
    assert "RLIMIT_DATA" in messages
    assert str(300 * MiB) in messages


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


def test_a_data_limit_above_its_address_limit_is_refused() -> None:
    with pytest.raises(ValidationError, match="extraction_data_limit_bytes"):
        SandboxSettings(extraction_data_limit_bytes=700 * MiB)
    with pytest.raises(ValidationError, match="interactive_data_limit_bytes"):
        SandboxSettings(interactive_data_limit_bytes=500 * MiB)
    equal = SandboxSettings(interactive_data_limit_bytes=448 * MiB)
    assert equal.interactive_data_limit_bytes == 448 * MiB


def test_a_disabled_sandbox_is_warned_about_when_the_settings_load(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LEMELY_SANDBOX__ENABLED", "false")
    monkeypatch.setattr(sandbox, "load_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    sandbox.sandbox_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="lemely.runtime.sandbox"):
            assert sandbox.sandbox_settings().enabled is False
            sandbox.sandbox_settings()
    finally:
        sandbox.sandbox_settings.cache_clear()

    warnings = [r for r in caplog.records if r.name == "lemely.runtime.sandbox"]
    assert len(warnings) == 1
    assert "sandbox_disabled" in warnings[0].getMessage()


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


def _process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_one_deadline_covers_the_whole_stream(worker: ChildWorker) -> None:
    worker.call(f"{_T}.pid", timeout=10, result_type=int)  # a warm child
    received: list[int] = []

    started = time.monotonic()
    with pytest.raises(SandboxTimeout):
        for item in worker.stream(f"{_T}.slow_count", 5, 1.0, timeout=2.5, item_type=int):
            received.append(item)
    elapsed = time.monotonic() - started

    assert received == [0, 1, 2]
    assert elapsed < 3.0
    assert worker.last_outcome == "timeout"
    assert worker.pid() is None


def test_the_lock_wait_shrinks_the_call_budget(worker: ChildWorker) -> None:
    worker.call(f"{_T}.pid", timeout=10, result_type=int)  # a warm child
    errors: list[BaseException] = []

    def hold() -> None:
        try:
            worker.call(f"{_T}.sleep_for", 0.4, timeout=5, result_type=type(None))
        except BaseException as exc:  # reported below, never swallowed
            errors.append(exc)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        time.sleep(0.05)
        started = time.monotonic()
        # ~0.35 s waiting for the lock leaves ~0.25 s of the 0.6 s budget,
        # too little for a 0.3 s target.
        with pytest.raises(SandboxTimeout):
            worker.call(f"{_T}.sleep_for", 0.3, timeout=0.6, result_type=type(None))
        elapsed = time.monotonic() - started
    finally:
        holder.join(timeout=10)

    assert errors == []
    assert 0.5 <= elapsed < 0.8


def test_a_dropped_stream_is_finalised_and_frees_the_worker(worker: ChildWorker) -> None:
    items = worker.stream(f"{_T}.slow_count", 3, 5.0, timeout=30, item_type=int)
    assert next(items) == 0
    old_pid = worker.pid()
    assert old_pid is not None

    del items
    gc.collect()

    assert worker._lock.acquire(blocking=False)
    worker._lock.release()
    assert _process_gone(old_pid)
    assert worker.last_outcome == "interrupted"


def test_shutdown_returns_within_its_bound_behind_a_suspended_stream(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream kept alive (by a traceback, say) holds the lock; shutdown must
    not wait for it forever. It kills the child; the holder's next pipe
    operation then sees the crash and cleans up."""
    monkeypatch.setattr(sandbox, "_SHUTDOWN_LOCK_WAIT_SECONDS", 0.5, raising=False)
    items = worker.stream(f"{_T}.slow_count", 3, 5.0, timeout=30, item_type=int)
    try:
        assert next(items) == 0
        old_pid = worker.pid()
        assert old_pid is not None
        stopped = threading.Event()

        def stop() -> None:
            worker.shutdown()
            stopped.set()

        started = time.monotonic()
        threading.Thread(target=stop, daemon=True).start()
        assert stopped.wait(timeout=5)
        assert time.monotonic() - started < 2.0

        with pytest.raises(SandboxCrash):
            next(items)
        assert worker.last_outcome == "crash"
        assert _process_gone(old_pid)
    finally:
        items.close()  # releases the lock if shutdown is still waiting on it


def test_pid_is_none_once_the_child_has_died(worker: ChildWorker) -> None:
    old_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)

    os.kill(old_pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while worker.pid() is not None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker.pid() is None
    assert worker.call(f"{_T}.pid", timeout=10, result_type=int) != old_pid


def test_a_target_outside_lemely_is_refused_in_the_child_and_in_process(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A shell command that would succeed (and return 0) if it ran.
    with pytest.raises(SandboxError, match=r"os\.system"):
        worker.call("os.system", "true", timeout=10, result_type=int)
    # An attribute of a lemely module that is not lemely code (python-dotenv).
    with pytest.raises(SandboxError, match="dotenv_values"):
        worker.call("lemely.runtime.config.dotenv_values", timeout=10, result_type=dict)
    # lemely code reached through a module that is not: the module is never
    # imported (an import alone can run code).
    with pytest.raises(SandboxError, match="sandbox_fixtures"):
        worker.call(
            "tests.sandbox_fixtures.SandboxSettings", timeout=10, result_type=SandboxSettings
        )

    monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=False))
    with pytest.raises(ValueError, match=r"os\.system"):
        worker.call("os.system", "true", timeout=10, result_type=int)
    with pytest.raises(ValueError, match="dotenv_values"):
        worker.call("lemely.runtime.config.dotenv_values", timeout=10, result_type=dict)
    with pytest.raises(ValueError, match="sandbox_fixtures"):
        worker.call(
            "tests.sandbox_fixtures.SandboxSettings", timeout=10, result_type=SandboxSettings
        )
