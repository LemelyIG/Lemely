"""`ChildWorker` (#260): a killable, rlimit-bounded child process for scan work.

Every test below runs its target in a real ``spawn``ed child (the targets
live in :mod:`tests.sandbox_targets`), except the one that switches the
sandbox off. Each worker made here is shut down in teardown, and the
``sandboxed`` fixture shuts the two module workers down on both sides of a
test, so no child outlives the test that started it.
"""

from __future__ import annotations

import ast
import gc
import logging
import math
import os
import re
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
_REPO_ROOT = Path(__file__).resolve().parents[1]
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
    # The child's ready message reports what it actually applied, the OOM
    # priority with the limits.
    assert worker.applied_limits == (256 * MiB, 512 * MiB, 0, 1000)


@pytest.mark.skipif(sys.platform != "linux", reason="oom_score_adj is Linux's")
def test_the_kernel_kills_a_worker_child_before_the_web_server(worker: ChildWorker) -> None:
    """Owner decision (Task 11 re-review): with the 2 GiB budget's margin at
    ~44 MiB, a worker child is the OOM killer's first choice (score adjust
    1000, the most), so an exhausted instance costs one request a 422, not
    the web server. The parent keeps its own, lower score."""
    worker.call(f"{_T}.pid", timeout=10, result_type=int)
    child = worker.pid()
    assert child is not None

    with open(f"/proc/{child}/oom_score_adj", encoding="ascii") as adj:
        assert adj.read().strip() == "1000"
    with open("/proc/self/oom_score_adj", encoding="ascii") as adj:
        assert int(adj.read()) < 1000


_CLAMPED_LIMIT_SCRIPT = textwrap.dedent(
    """
    import logging, resource
    resource.setrlimit(resource.RLIMIT_DATA, (300 * 2**20, 300 * 2**20))
    from lemely.runtime import sandbox
    from lemely.runtime.config import SandboxSettings
    sandbox.sandbox_settings = lambda: SandboxSettings()
    sandbox._EXTRA_TARGET_MODULES = frozenset({"tests.sandbox_targets"})
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


#: A path-run script whose top level imports ``lemely.web``, as
#: ``scripts/e2e_server.py`` does. ``spawn`` used to re-run it in the child
#: before the limits were set: ~827 MB ``VmData``, over both limits.
_PATH_RUN_SCRIPT = textwrap.dedent(
    """
    import lemely.web  # noqa: F401
    from lemely.runtime import sandbox
    from lemely.runtime.config import SandboxSettings
    sandbox.sandbox_settings = lambda: SandboxSettings()
    sandbox._EXTRA_TARGET_MODULES = frozenset({"tests.sandbox_targets"})
    worker = sandbox.ChildWorker(
        "path-run",
        limits=lambda s: (s.interactive_data_limit_bytes, s.interactive_address_limit_bytes),
    )
    if __name__ == "__main__":
        import sys
        try:
            print(worker.call("tests.sandbox_targets.startup_state", timeout=60, result_type=tuple))
            print(sys.modules["__main__"].__spec__)
        finally:
            worker.shutdown()
    """
)


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc/self/status in the child")
def test_a_path_run_parent_main_is_not_re_run_in_the_child(tmp_path: Path) -> None:
    """The child starts without the script's imports, under its limits, and the call succeeds."""
    script = tmp_path / "path_run_parent.py"
    script.write_text(_PATH_RUN_SCRIPT, encoding="utf-8")

    proc = subprocess.run(  # noqa: S603 -- our own interpreter and a fixed script
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )

    assert proc.returncode == 0, proc.stderr
    state, parent_spec = proc.stdout.strip().splitlines()[-2:]
    vm_data, web_loaded, child_main_file = ast.literal_eval(state)
    # The child's main is spawn's own -c stub, not this script re-run.
    assert (web_loaded, child_main_file) == (False, None)
    # About 26 MiB measured; the re-run script put it at ~827 MB.
    assert vm_data < 128 * MiB
    # The script's own spec (None: it was run by path) is back after the start.
    assert parent_spec == "None"


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
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )

    assert proc.returncode == 0, proc.stderr
    applied, messages = proc.stdout.strip().splitlines()[-2:]
    assert applied == str((300 * MiB, 1024 * MiB, 0, 1000))
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

    # Which subclass depends on where the allocation failed (a Python
    # MemoryError or a recognised MuPDF/pdfium allocation failure ->
    # SandboxMemory, any other library error -> SandboxError, an abort ->
    # SandboxCrash); the claim is recovery and a bounded parent.
    assert isinstance(failure.value, SandboxError | SandboxMemory | SandboxCrash)
    record_property("render_failure", f"{type(failure.value).__name__}: {failure.value}")
    assert worker.call(f"{_T}.pid", timeout=30, result_type=int) > 0
    assert grown < 32 * MiB


def test_shutdown_clears_the_start_cool_down(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A context of its own: a bare monkeypatch.undo() would also undo the
    # sandboxed fixture's patches (settings and the test-target allowlist).
    with monkeypatch.context() as patch:
        patch.setattr(worker, "_spawn", lambda: False)
        with pytest.raises(SandboxUnavailable):
            worker.call(f"{_T}.pid", timeout=5, result_type=int)
        assert worker.last_outcome == "unavailable"

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
    assert (
        settings.sandbox.interactive_data_limit_bytes
        == SandboxSettings().interactive_data_limit_bytes
    )


def test_a_data_limit_above_its_address_limit_is_refused() -> None:
    defaults = SandboxSettings()
    with pytest.raises(ValidationError, match="extraction_data_limit_bytes"):
        SandboxSettings(extraction_data_limit_bytes=defaults.extraction_address_limit_bytes + MiB)
    with pytest.raises(ValidationError, match="interactive_data_limit_bytes"):
        SandboxSettings(interactive_data_limit_bytes=defaults.interactive_address_limit_bytes + MiB)
    equal = SandboxSettings(interactive_data_limit_bytes=defaults.interactive_address_limit_bytes)
    assert equal.interactive_data_limit_bytes == defaults.interactive_address_limit_bytes


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
        # The holder must own the lock before the clock starts: on a loaded
        # runner a fixed sleep let this thread win it instead. Bounded, so a
        # holder that never starts fails here rather than hanging.
        waited_until = time.monotonic() + 5.0
        while not worker._lock.locked():
            assert time.monotonic() < waited_until, "the holder never took the worker's lock"
            time.sleep(0.001)
        started = time.monotonic()
        # Up to ~0.4 s waiting for the lock leaves ~0.2 s of the 0.6 s
        # budget, too little for a 0.3 s target.
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
    monkeypatch.setattr(sandbox, "_SHUTDOWN_LOCK_WAIT_SECONDS", 0.5)
    items = worker.stream(f"{_T}.slow_count", 3, 5.0, timeout=30, item_type=int)
    try:
        assert next(items) == 0
        old_pid = worker.pid()
        assert old_pid is not None
        # A stale cool-down must not outlive a shutdown, even a timed-out one.
        worker._start_failed_at = time.monotonic()
        stopped = threading.Event()

        def stop() -> None:
            worker.shutdown()
            stopped.set()

        started = time.monotonic()
        threading.Thread(target=stop, daemon=True).start()
        assert stopped.wait(timeout=5)
        assert time.monotonic() - started < 2.0
        assert worker._start_failed_at is None

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


def test_test_targets_run_only_where_the_fixtures_opt_in(
    worker: ChildWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production allows ``lemely`` code alone; ``tests.sandbox_targets`` is
    added by the ``sandboxed`` / ``in_process_sandbox`` fixtures."""
    assert frozenset({_T}) == sandbox._EXTRA_TARGET_MODULES
    monkeypatch.setattr(sandbox, "_EXTRA_TARGET_MODULES", frozenset())

    # The worker has not started yet, so its child gets the production list.
    with pytest.raises(SandboxError, match="sandbox_targets"):
        worker.call(f"{_T}.pid", timeout=10, result_type=int)
    monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=False))
    with pytest.raises(ValueError, match="sandbox_targets"):
        worker.call(f"{_T}.pid", timeout=10, result_type=int)


def _white_rgb_png(width: int, height: int) -> bytes:
    """A white 8-bit RGB PNG, built row by row: a few KB of file, ``3 * width * height`` decoded."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    compressor = zlib.compressobj(6)
    row = b"\x00" + b"\xff\xff\xff" * width
    idat = b"".join(compressor.compress(row) for _ in range(height)) + compressor.flush()
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def test_an_allocation_failure_inside_mupdf_or_pdfium_is_recognised_by_class_and_text() -> None:
    """MuPDF has no memory error class: ``fz_malloc``/``fz_calloc``/``fz_realloc``
    throw ``FZ_ERROR_SYSTEM`` saying ``"malloc (N bytes) failed"``, and the
    same class also carries I/O failures. pypdfium2 names a bitmap it could
    not allocate. Only the class AND the allocator's text together count.
    A size computation that overflows (``"... failed (overflow)"``) is a
    malformed request, not memory running out, so it stays an error. The
    texts are MuPDF 1.29's own (``strings libmupdf.so.29.0``)."""
    from pymupdf import mupdf
    from pypdfium2 import PdfiumError

    for text in (
        "malloc (119076300 bytes) failed",
        "calloc (3 x 4 bytes) failed",
        "realloc (5 bytes) failed",
    ):
        assert sandbox._is_allocation_failure(mupdf.FzErrorSystem(text)), text
    assert sandbox._is_allocation_failure(
        PdfiumError("Failed to get bitmap buffer (null pointer returned)")
    )

    for text in (
        "calloc (3 x 4 bytes) failed (overflow)",
        "malloc array (3 x 4 bytes) failed (overflow)",
        "realloc array (3 x 4 bytes) failed (overflow)",
    ):
        assert not sandbox._is_allocation_failure(mupdf.FzErrorSystem(text)), text
    assert not sandbox._is_allocation_failure(mupdf.FzErrorSystem("cannot open file 'x'"))
    assert not sandbox._is_allocation_failure(mupdf.FzErrorFormat("malloc (1 bytes) failed"))
    assert not sandbox._is_allocation_failure(PdfiumError("Failed to load page."))
    assert not sandbox._is_allocation_failure(RuntimeError("code=2: malloc (1 bytes) failed"))
    assert not sandbox._is_allocation_failure(ValueError("Failed to get bitmap buffer"))


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_DATA bounds malloc on Linux")
def test_mupdf_running_out_of_memory_in_the_child_is_sandbox_memory(
    make_worker: WorkerFactory,
) -> None:
    """MuPDF decoding a colour image under a data limit too small for it (the
    failure Task 8 first met in the preview). Its ``FzErrorSystem`` is an
    allocation failure, so it is reported as memory, not as an error, and
    the child lives on. The failure's own text (the allocation's size) comes
    with it, for the logs; a Python ``MemoryError`` has no such text, so the
    message pins the MuPDF branch. The draw is a test target
    (``mupdf_draws_image``), the preview's old image path: an image scan is
    decoded by Pillow on every path now (final review R3, I1). A PDF page
    was tried instead and did not do: the preview draws it at most 842 px,
    so MuPDF decodes its image subsampled and nothing fails, and a crop of
    it under this limit failed in Python first (a bare ``MemoryError``)."""
    from tests.sandbox_targets import ONE_PIXEL_PNG

    worker = make_worker(1024 * MiB, 2048 * MiB)
    draw = f"{_T}.mupdf_draws_image"
    # A first draw imports MuPDF, so the limit below is set over what a warm
    # child already holds, on any machine.
    worker.call(draw, ONE_PIXEL_PNG, timeout=60, result_type=bytes)
    first_pid = worker.call(f"{_T}.pid", timeout=10, result_type=int)
    in_use = worker.call(f"{_T}._vm_data_bytes", timeout=10, result_type=int)

    with pytest.raises(SandboxFailure) as failure:
        worker.call(
            f"{_T}.lower_data_limit_then",
            in_use + 24 * MiB,
            draw,
            _white_rgb_png(4000, 4000),  # 48 MB decoded: MuPDF's malloc fails
            timeout=60,
            result_type=bytes,
        )

    assert type(failure.value) is SandboxMemory, repr(failure.value)
    assert re.fullmatch(
        r"lemely-test-worker ran out of memory: code=2: malloc \(\d+ bytes\) failed",
        str(failure.value),
    ), str(failure.value)
    assert worker.last_outcome == "memory"
    assert worker.call(f"{_T}.pid", timeout=10, result_type=int) == first_pid


def test_a_python_memory_error_is_sandbox_memory_with_the_bare_message(
    make_worker: WorkerFactory,
) -> None:
    worker = make_worker(256 * MiB, 1024 * MiB)
    with pytest.raises(SandboxMemory) as failure:
        worker.call(
            f"{_T}.lower_data_limit_then",
            96 * MiB,
            f"{_T}.allocate",
            512 * MiB,
            timeout=10,
            result_type=int,
        )
    assert str(failure.value) == "lemely-test-worker ran out of memory"


#: The 2 GiB worst case the owner accepted on 2026-10-05, in MiB, with every
#: term at its worst at once (``docs/ci-cd.md``, "Memory budget"; the
#: ``lemely.runtime.sandbox`` docstring). MEASURED peaks, resident: the web
#: process idle after start-up (``python -m lemely.web``; 237.4 MB), and one
#: marking run's share of it, the pages of the adversarial 40-page extraction
#: (40 incompressible pages at the 160 Mpx scan cap; 500.5 MB) plus
#: ``scan_hygiene`` on one of them (``VmHWM`` growth); multiprocessing's
#: ``resource_tracker`` (16.4 MB). LIMITS, read from the code: both workers'
#: ``RLIMIT_DATA``, the parse worker's ``RLIMIT_AS``, and the run cap
#: (``lemely.io.run_cap``).
_WEB_PROCESS_MIB = 226.4
_RUN_PAGES_MIB = 477.3
_RUN_SCAN_HYGIENE_MIB = 129.2
_RESOURCE_TRACKER_MIB = 15.6
#: The instance: Cloud Run's ``--memory=2Gi``.
_INSTANCE_MIB = 2048
#: Owner decision, 2026-10-05: the total above, 2640.5 MiB, a margin of
#: -592.5 MiB, accepted as the worst case. A change that adds to it (a
#: higher limit, a second run) should be a new decision, not a rounding.
_ACCEPTED_WORST_CASE_MIB = 2640.5


def test_the_default_limits_fit_the_accepted_worst_case() -> None:
    """The 2 GiB budget does not fit at worst, and the owner accepted that
    worst case (2026-10-05): both workers at their data limits, the web
    process idle, one marking run (its pages plus ``scan_hygiene``), the
    parse worker at its address limit and the resource tracker. This pins
    it, so a raised limit or a second concurrent run goes red."""
    from lemely.core.equivalence import _PARSE_WORKER_MEMORY_BYTES
    from lemely.io.run_cap import MAX_CONCURRENT_RUNS

    settings = SandboxSettings()
    total_mib = (
        (settings.extraction_data_limit_bytes + settings.interactive_data_limit_bytes) / MiB
        + _WEB_PROCESS_MIB
        + MAX_CONCURRENT_RUNS * (_RUN_PAGES_MIB + _RUN_SCAN_HYGIENE_MIB)
        + _PARSE_WORKER_MEMORY_BYTES / MiB
        + _RESOURCE_TRACKER_MIB
    )
    assert total_mib == pytest.approx(_ACCEPTED_WORST_CASE_MIB, abs=0.05), total_mib
    assert _INSTANCE_MIB - total_mib == pytest.approx(-592.5, abs=0.05)


def _next64(mib: float) -> int:
    return math.ceil(mib / 64) * 64


def test_the_default_limits_follow_the_measured_growth_rule() -> None:
    """Task 11 (owner decision on review round 2): ``RLIMIT_DATA =
    next64(baseline + 1.5 x (worst - baseline))``, 1.5x headroom on what the
    child allocates over its warm baseline; ``RLIMIT_AS = max(next64(1.25 x
    worst VmPeak), RLIMIT_DATA + 128)``. The measured MiB are recorded in the
    ``lemely.runtime.sandbox`` docstring; a re-measurement changes them here.
    The interactive worker's worst is the crop of a WHOLE page of a keyed
    transparent 159 Mpx 1-bit PNG (final fix B, 2026-10-05), worse than
    every path in turn in one child (428 / 518): next64(66.71 + 1.5 x
    364.8) = 640 MiB, and max(next64(1.25 x 521.0), 640 + 128) = 768 MiB
    (owner decision, 2026-10-05)."""
    baseline = 66.71  # warm child: the render modules imported
    measured = {  # worker: (worst VmData, worst VmPeak), fresh or in turn
        "extraction": (417.09, 506.6),
        "interactive": (431.5, 521.0),
    }
    settings = SandboxSettings()
    for worker, (worst_data, worst_peak) in measured.items():
        data = _next64(baseline + 1.5 * (worst_data - baseline))
        address = max(_next64(1.25 * worst_peak), data + 128)
        assert getattr(settings, f"{worker}_data_limit_bytes") == data * MiB, worker
        assert getattr(settings, f"{worker}_address_limit_bytes") == address * MiB, worker


def test_the_extraction_timeout_is_the_owner_decision() -> None:
    """Task 11 review, owner decision 2: 180 s, counting any wait for the
    worker (``test_the_lock_wait_shrinks_the_call_budget``)."""
    assert SandboxSettings().extraction_timeout_seconds == 180.0


def test_measure_reports_peaks_and_time_of_a_target_in_the_child(worker: ChildWorker) -> None:
    """``tests.sandbox_targets.measure`` (Task 11 brief; Task 21 uses it):
    ``VmPeak``, ``VmHWM``, the largest ``VmData`` sampled every 25 ms, and
    wall seconds, all of the target run in the child, an iterator drained."""
    held = 64 * MiB
    before = worker.call(f"{_T}._vm_data_bytes", timeout=30, result_type=int)

    result = worker.call(f"{_T}.measure", f"{_T}.hold", held, 0.2, timeout=30, result_type=dict)

    assert set(result) == {"vm_peak", "vm_hwm", "vm_data_max", "seconds"}
    assert result["vm_data_max"] >= before + held
    assert result["vm_hwm"] >= held
    assert result["vm_peak"] >= result["vm_hwm"]
    assert 0.2 <= result["seconds"] < 10

    drained = worker.call(f"{_T}.measure", f"{_T}.slow_count", 4, 0.1, timeout=30, result_type=dict)
    assert drained["seconds"] >= 0.3  # three pauses: every item was pulled
