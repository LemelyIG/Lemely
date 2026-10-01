"""Targets for `lemely.runtime.sandbox.ChildWorker` tests, run in the child.

A worker names its target by dotted path, so every function here is called in
a ``spawn``ed child as ``tests.sandbox_targets.<name>``. The module imports
only the standard library and ``lemely.runtime.errors`` at module level
(``reject`` imports ``lemely.io`` inside the function), so the child can
import it cheaply under its limits.
"""

from __future__ import annotations

import importlib
import os
import resource
import struct
import time
import zlib
from collections.abc import Callable, Iterable, Iterator
from typing import cast

from lemely.runtime.errors import LemelyError


def pid() -> int:
    return os.getpid()


def sleep_for(seconds: float) -> None:
    time.sleep(seconds)


def allocate(n_bytes: int) -> int:
    """Allocate and touch ``n_bytes``; a negative size is a ``ValueError``."""
    block = bytearray(n_bytes)
    block[::4096] = b"\x01" * len(block[::4096])
    return len(block)


def crash() -> None:
    os._exit(3)


def reject(message: str, reason: str) -> None:
    from lemely.io.scan_limits import ScanRejectedError

    raise ScanRejectedError(message, reason=reason)


class _KeywordOnlyRejection(LemelyError):
    """A refusal that pickles but cannot be rebuilt from its ``args``."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def reject_unrebuildable(message: str) -> None:
    raise _KeywordOnlyRejection(message, reason="malformed")


def count_up(n: int) -> Iterator[int]:
    yield from range(n)


def slow_count(n: int, pause: float) -> Iterator[int]:
    """Yield ``0..n-1`` with ``pause`` seconds between items."""
    for i in range(n):
        if i:
            time.sleep(pause)
        yield i


def rlimits() -> tuple[int, int, int]:
    return (
        resource.getrlimit(resource.RLIMIT_DATA)[0],
        resource.getrlimit(resource.RLIMIT_AS)[0],
        resource.getrlimit(resource.RLIMIT_CORE)[0],
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


#: A valid 1x1 white greyscale PNG.
ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff"))
    + _png_chunk(b"IEND", b"")
)


def record_window(path: str, hold_seconds: float, *ignored: object) -> bytes:
    """Append ``"<start> <end>\\n"`` (``time.monotonic()``) to ``path`` around a hold.

    Stands in for a render target, so a test can see whether two calls ever
    overlapped. Returns a 1x1 PNG.
    """
    start = time.monotonic()
    time.sleep(hold_seconds)
    end = time.monotonic()
    with open(path, "a", encoding="ascii") as log:
        log.write(f"{start} {end}\n")
    return ONE_PIXEL_PNG


def _resolve(target: str) -> Callable[..., object]:
    module_name, _, attribute = target.rpartition(".")
    return getattr(importlib.import_module(module_name), attribute)


def _vm_hwm_bytes() -> int:
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("no VmHWM in /proc/self/status")


def peak_rss_of(target: str, *args: object) -> tuple[int, object]:
    """``(VmHWM growth in bytes, outcome)`` of running ``target(*args)`` here.

    The target is imported before the high-water mark is reset, so import
    cost is not counted. The outcome is the number of items for an iterator
    or a list (pages, for a render), and the result itself otherwise, so a
    measurement never ships the rendered pages back to the parent.
    """
    function = _resolve(target)
    with open("/proc/self/clear_refs", "w", encoding="ascii") as clear:
        clear.write("5")
    before = _vm_hwm_bytes()
    result = function(*args)
    outcome: object
    if isinstance(result, Iterator):
        outcome = sum(1 for _ in cast("Iterable[object]", result))
    elif isinstance(result, list):
        outcome = len(result)
    else:
        outcome = result
    return _vm_hwm_bytes() - before, outcome


def lower_data_limit_then(data_limit: int, target: str, *args: object) -> object:
    """Run ``target(*args)`` with ``RLIMIT_DATA`` lowered to ``data_limit``.

    The target is imported first, so its import is not starved, and the soft
    limit is restored afterwards, so the child's next call runs under the
    limit it was started with.
    """
    function = _resolve(target)
    soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
    resource.setrlimit(resource.RLIMIT_DATA, (data_limit, hard))
    try:
        return function(*args)
    finally:
        resource.setrlimit(resource.RLIMIT_DATA, (soft, hard))


def oom(*ignored: object) -> bytes:
    """Touch a 1 GiB ``bytearray``: past any worker's ``RLIMIT_DATA``.

    Stands in for a render target (it takes and ignores the route's
    arguments), so a route test can see a ``SandboxMemory`` arrive.
    """
    allocate(1024 * 1024 * 1024)
    return ONE_PIXEL_PNG


#: The file :func:`record_window_from_env` appends to, named in the environment
#: because a render target's arguments are the route's, not the test's.
WINDOW_FILE_ENV = "LEMELY_TEST_WINDOW_FILE"


def record_window_from_env(*ignored: object) -> bytes:
    """:func:`record_window` with a 0.4 s hold, into the file ``$LEMELY_TEST_WINDOW_FILE`` names.

    The child inherits the variable when it is started, so a test sets it
    before the worker's first call.
    """
    return record_window(os.environ[WINDOW_FILE_ENV], 0.4)


def boom(*ignored: object) -> bytes:
    """Fail with a message that must never reach a client.

    Stands in for a render target (it takes and ignores the route's
    arguments), so a route test can see that the renderer's own text stays
    in the logs and out of the response.
    """
    raise RuntimeError("DISTINCTIVE-RENDERER-TEXT")
