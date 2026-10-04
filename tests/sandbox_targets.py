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
import threading
import time
import weakref
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
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


def render_fails_on_second_page(scan_path: object, dpi: float) -> Iterator[object]:
    """``iter_scan_pages(scan_path, dpi)`` with pdfium's render raising on page two.

    Stands in for the extraction target (Task 10 review, item 1): a
    ``ValueError`` part-way through a scan must reach the caller as a failure,
    never as a shorter scan. The patch lives only as long as the stream, so
    the child's next call renders normally.
    """
    from unittest.mock import patch

    import pypdfium2 as pdfium

    from lemely.io.rasterise import iter_scan_pages

    real_render = pdfium.PdfPage.render
    calls = 0

    def render(page: object, *args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("page two would not render")
        return real_render(page, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(pdfium.PdfPage, "render", render):
        yield from iter_scan_pages(scan_path, dpi)  # type: ignore[arg-type]


#: Room left above the child's current ``VmData`` by
#: :func:`starved_iter_scan_pages`: far below one page's render at 400 DPI
#: (a ~40 MB bitmap plus its ~30 MB RGB copy), whatever the imports cost.
STARVED_HEADROOM_BYTES = 16 * 1024 * 1024


def _vm_data_bytes() -> int:
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            if line.startswith("VmData:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("no VmData in /proc/self/status")


def starved_iter_scan_pages(scan_path: object, dpi: float) -> Iterator[object]:
    """``iter_scan_pages(scan_path, dpi)`` under ``RLIMIT_DATA`` = current ``VmData`` + headroom.

    Stands in for the extraction target (Task 10 review, item 5). The
    rasterise module is imported first, and the limit is set relative to what
    the child already uses, so the test does not depend on how much a given
    machine's imports cost. The soft limit is restored when the stream ends,
    however it ends.
    """
    from lemely.io.rasterise import iter_scan_pages

    soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
    resource.setrlimit(resource.RLIMIT_DATA, (_vm_data_bytes() + STARVED_HEADROOM_BYTES, hard))
    try:
        yield from iter_scan_pages(scan_path, dpi)  # type: ignore[arg-type]
    finally:
        resource.setrlimit(resource.RLIMIT_DATA, (soft, hard))


@dataclass
class TrackedItem:
    """One item of :func:`tracked_items`: whether the item before it was still alive."""

    index: int
    previous_alive: bool


def tracked_items(n: int) -> Iterator[TrackedItem]:
    """Yield ``n`` items, each recording whether its predecessor was still referenced.

    For ``sandbox._serve`` (Task 10 review, item 3): a streaming child must
    drop each item once it is sent, so it holds one at a time.
    """
    previous: weakref.ref[TrackedItem] | None = None
    for index in range(n):
        item = TrackedItem(index, previous is not None and previous() is not None)
        previous = weakref.ref(item)
        yield item
        del item


def hold(n_bytes: int, seconds: float) -> int:
    """Allocate and touch ``n_bytes``, keep them ``seconds``, then let them go."""
    block = bytearray(n_bytes)
    block[::4096] = b"\x01" * len(block[::4096])
    time.sleep(seconds)
    return len(block)


#: How often :func:`measure` samples ``VmData`` (the Task 11 brief: 25 ms).
MEASURE_INTERVAL_SECONDS = 0.025


def _status_bytes(*fields: str) -> dict[str, int]:
    found: dict[str, int] = {}
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            key = line.split(":", 1)[0]
            if key in fields:
                found[key] = int(line.split()[1]) * 1024
    return found


def measure(target: str, *args: object) -> dict[str, int | float]:
    """What running ``target(*args)`` here costs: the Task 11 measurement, in the child.

    Returns, in bytes but the last:

    * ``vm_peak``: ``VmPeak``, the largest address space this process has
      ever had, so a fresh child is needed to pin it on one target;
    * ``vm_hwm``: ``VmHWM``, reset before the call, so the call's resident peak;
    * ``vm_data_max``: the largest ``VmData`` (what ``RLIMIT_DATA`` bounds),
      sampled every 25 ms by a thread, plus once before and once after; the
      thread's own stack counts in it;
    * ``seconds``: wall time.

    The target is imported first, so its import is not counted. An iterator
    it returns is drained, each item dropped as it comes. Task 21 measures
    its render path with this.
    """
    function = _resolve(target)
    with open("/proc/self/clear_refs", "w", encoding="ascii") as clear:
        clear.write("5")
    samples = [_vm_data_bytes()]
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(MEASURE_INTERVAL_SECONDS):
            samples.append(_vm_data_bytes())

    sampler = threading.Thread(target=sample, name="measure-vmdata", daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        result = function(*args)
        if isinstance(result, Iterator):
            for _item in cast("Iterable[object]", result):
                pass
        del result
    finally:
        seconds = time.perf_counter() - started
        stop.set()
        sampler.join()
    samples.append(_vm_data_bytes())
    peaks = _status_bytes("VmPeak", "VmHWM")
    return {
        "vm_peak": peaks["VmPeak"],
        "vm_hwm": peaks["VmHWM"],
        "vm_data_max": max(samples),
        "seconds": seconds,
    }


#: The bilevel-in-PDF measurement's decoded-pixel ceiling (Task 21, #273): a
#: 10 000 x 15 900 image, 159 Mpx, is over the walk's 40 Mpx colour cap.
BILEVEL_PDF_MAX_DECODE_PX = 160_000_000


def _extract_bilevel_pdf(path: str) -> Iterator[object]:
    from pathlib import Path

    from lemely.io.rasterise import iter_scan_pages

    return iter_scan_pages(Path(path), 200.0)


def _crop_bilevel_pdf(path: str) -> bytes:
    from pathlib import Path

    from lemely.io.scan_render import crop_pdf_scan

    return crop_pdf_scan(Path(path).read_bytes(), 0, [100, 100, 300, 400])


def _preview_bilevel_pdf(path: str) -> bytes:
    from pathlib import Path

    from lemely.io.scan_render import render_preview_png

    return render_preview_png(Path(path).read_bytes())


_BILEVEL_PDF_PATHS = {
    "extraction": "_extract_bilevel_pdf",
    "crop": "_crop_bilevel_pdf",
    "preview": "_preview_bilevel_pdf",
}


def bilevel_pdf_paths(path: str, mode: str) -> dict[str, object]:
    """Measure one render path over a 160 Mpx bilevel PDF in this child (Task 21, #273).

    ``mode`` is ``"extraction"`` (``iter_scan_pages(path, 200.0)``),
    ``"crop"`` (``crop_pdf_scan(data, 0, [100, 100, 300, 400])``) or
    ``"preview"`` (``render_preview_png(data)``). The PDF walk refuses the
    image at its 40 Mpx colour cap, so the child lifts
    ``pdf_content_walk.MAX_DECODE_PX`` (read at call time) to
    :data:`BILEVEL_PDF_MAX_DECODE_PX` first; nothing restores it, the child
    being a throwaway. Returns :func:`measure`'s numbers plus the soft
    ``RLIMIT_DATA`` and ``RLIMIT_AS`` the child ran under.
    """
    from lemely.io import pdf_content_walk

    setattr(pdf_content_walk, "MAX_DECODE_PX", BILEVEL_PDF_MAX_DECODE_PX)  # noqa: B010
    numbers: dict[str, object] = dict(measure(f"{__name__}.{_BILEVEL_PDF_PATHS[mode]}", path))
    numbers["rlimit_data"] = resource.getrlimit(resource.RLIMIT_DATA)[0]
    numbers["rlimit_as"] = resource.getrlimit(resource.RLIMIT_AS)[0]
    return numbers
