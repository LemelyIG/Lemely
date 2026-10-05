"""A killable, memory-limited child process for scan work (#260).

MuPDF, pdfium and Pillow decode untrusted scans in C. A hostile or merely
huge scan can make them allocate far past what the web process can spare, and
a C-level loop holds the GIL, so neither a thread timeout nor a Python-level
check can stop it once it has started. A child process can be both bounded
and killed. :class:`ChildWorker` keeps one such child per worker, started
lazily and reused, and runs a named function (a *target*) in it:

* The child runs under ``RLIMIT_DATA`` (heap and private mappings: the bound
  that matters) and a looser ``RLIMIT_AS`` backstop (address space, which also
  counts shared libraries and reserved-but-untouched arenas). A Python
  ``MemoryError`` in the child is reported (:class:`SandboxMemory`) and the
  child lives on. So is an allocation failure a C library reports as its own
  exception, recognised by class and text (:func:`_is_allocation_failure`):
  MuPDF's ``FzErrorSystem`` saying ``"malloc (N bytes) failed"`` (MuPDF has
  no memory error class; ``FZ_ERROR_SYSTEM`` also carries I/O failures, and
  a size that overflows, ``"... failed (overflow)"``, stays an error), and
  pypdfium2's ``PdfiumError`` for a bitmap it could not get. The failure's
  own text, which names the allocation's size, rides in the
  :class:`SandboxMemory` message for the logs. pdfium's own
  allocator aborts on failure, which ends the child (:class:`SandboxCrash`),
  and a failure MuPDF reports some other way (inside the PDF rewrite it
  surfaces as an ``uncheckable`` refusal) is not recognised. Callers
  therefore treat every :class:`SandboxFailure` alike.
* A call that outlives its timeout kills the child; the next call respawns it.
* A :class:`~lemely.runtime.errors.LemelyError` raised by the target (a scan
  refusal) crosses the pipe intact, pickled with its ``args``, and is raised
  again in the caller. Any other exception becomes a :class:`SandboxError`
  carrying its ``repr``, for the logs only.
* The child never runs the parent's ``__main__``. ``spawn`` re-runs a
  path-run script (or a ``-m`` module not named ``__main__``) in the child
  before the limits are set, so a script that imported ``lemely.web`` at
  its top level left the child at ~827 MB ``VmData``, over both limits, and
  every scan failed (final review R1, Important 1).
  :func:`_start_without_parent_main` hides it for the start.

Two module workers split the work so a long extraction never blocks an
interactive request: :data:`EXTRACTION_WORKER` (extraction and the upload
check) and :data:`INTERACTIVE_WORKER` (preview and crop). Their limits and
timeouts are :class:`~lemely.runtime.config.SandboxSettings`, read once per
process through :func:`sandbox_settings`.

``lemely.runtime`` may not import ``lemely.io``, ``lemely.core`` or
``lemely.app`` (import-linter), so a target is named by dotted path
(``"lemely.io.rasterise.rasterise_pdf_to_pages"``) and imported in the child
when first called, and the child sorts exceptions by ``LemelyError`` alone.
Target names are fixed strings in the calling code, never user input; even
so, only ``lemely`` code can be named (tests add their own target module,
see :data:`_EXTRA_TARGET_MODULES`), so a
stray name can never run, say, ``os.system``.

This is a RESOURCE boundary (memory and time), not a privilege boundary. The
child runs as the same user, inherits the parent's environment (secrets
included) and file system access, and the parent unpickles whatever the
child sends back. It contains a decoder that runs away; it does not contain
one that has been taken over.

For the routes that use it (Task 10):

* :meth:`ChildWorker.stream` is a generator, so it takes the lock at the
  first ``next()``, not when it is called. A route that must answer 503 when
  the worker is busy has to prime the stream with one ``next()`` before it
  returns a ``StreamingResponse``. Close every stream (``contextlib.closing``
  or ``try/finally``): an abandoned one holds the worker until it is
  garbage-collected.
* The time to (re)start a child is outside the caller's budget: a call's
  ``timeout`` covers the lock wait and the work, and a start has its own
  bound, ``start_timeout_seconds``. A cold call can take up to that much
  longer than its ``timeout``.

Measured in this venv (Linux, CPython 3.13, 2026-10-01): a cold start, from
``spawn`` to ``("ready", None)``, takes 0.16-0.18 s; a warm round trip to a
trivial target about 0.02 ms. At ready the child is about 41 MB resident,
``VmData`` 26 MB and ``VmSize`` 65 MB; with the render modules imported
(``lemely.io.rasterise``, ``scan_render``, ``scan_limits``) it is 79 MiB
resident, ``VmData`` 67 MiB and ``VmSize`` 150 MiB.

The limits (Task 11, #260; measured 2026-10-04 on Linux 7.2 x86_64, CPython
3.13.12, pymupdf 1.28.0 / MuPDF 1.29.0, pypdfium2 5.11.0 / pdfium 7920,
Pillow 12.2.0). Every path ran through its real worker on the worst scan of
each kind the upload check admits, every mode and depth at its own ceiling
(``lemely.io._scan_common.decode_pixel_cap``), in a fresh warm child under
4 GiB / 8 GiB limits. ``Peak`` is ``VmPeak`` and ``HWM`` ``VmHWM`` at the
end of the call, ``Data`` the largest ``VmData`` sampled from the parent
every 5 ms, ``need`` the smallest ``RLIMIT_DATA`` (8 MiB steps, a fresh
child per try) the path completes under, all in MiB; ``s`` is wall seconds.
The PDFs: 40 A4 pages each a 2480 x 3508 1-bit image (155 Mpx at 200 dpi);
40 A4 pages each a different 4960 x 7016 RGB JPEG (23 MiB, under the upload
cap); 3 A4 pages each a 4960 x 7016 RGB image, Flate or JPEG. TIFFs hold the
whole image in one Deflate strip, the most a TIFF can make a decoder hold::

    extraction: extract | upload check
                         Peak  HWM Data need     s    Peak  HWM Data need     s
    PDF 40p 1-bit         208  141  124  112  5.51     152   84   68   72  0.04
    PDF 40p RGB JPEG      287  221  203  160 33.20     196  124  112  120  0.65
    PDF 3p RGB Flate      206  140  123  120  1.13     150   83   67   72  0.01
    PDF 3p RGB JPEG       240  169  156  136  3.27     167   94   83   88  0.20
    1-bit PNG 159Mpx      471  394  382  384  0.42     159   81   69   72  0.02
    1-bit TIFF 160Mpx     473  396  383  384  0.43     158   81   68   72  0.02
    L TIFF 160Mpx         464  386  375  376  0.56     159   81   70   72  0.02
    I;16 PNG 80Mpx        406  328  316  320  0.72     158   81   69   72  0.02
    I;16 TIFF 80Mpx       463  387  374  376  0.48     158   81   69   72  0.02
    RGB JPEG 40Mpx        222  145  133  136  1.51     165   93   82   80  0.03
    RGB PNG 34.8Mpx       324  248  235  240  0.37     159   81   70   72  0.02
    RGB PNG 39.7Mpx       349  271  259  264  0.41     158   81   69   72  0.02
    RGB TIFF 40Mpx        426  348  336  344  0.44     159   81   70   72  0.02
    LA PNG 40Mpx          501  425  412  416  0.43     159   81   70   72  0.02
    P PNG 40Mpx           387  310  297  304  0.33     158   81   69   72  0.02
    P BMP RLE 40Mpx       391  314  302  304  0.39     159   81   70   72  0.02
    RGBA PNG 30Mpx        416  338  326  328  0.40     158   81   69   72  0.02
    RGBA TIFF 30Mpx       417  339  327  328  0.42     159   81   70   72  0.02
    CMYK TIFF 30Mpx       416  339  326  328  0.45     158   81   69   72  0.02
    CMYK JPEG 30Mpx       216  139  126  128  0.21     161   84   72   72  0.02
    I TIFF 30Mpx          388  310  298  304  0.38     158   81   69   72  0.02
    F TIFF 30Mpx          387  310  297  304  0.39     159   81   70   72  0.02
    RGB16 PNG 20Mpx       254  177  164  168  0.27     158   81   69   72  0.02
    RGB16 TIFF 20Mpx      350  272  260  264  0.33     158   81   69   72  0.02
    RGBA16 PNG 15Mpx      273  196  183  184  0.44     158   81   69   72  0.03
    RGBA16 TIFF 15Mpx     331  253  241  248  0.46     159   81   70   72  0.02
    LA16 PNG 15Mpx        273  196  183  184  0.35     158   81   69   72  0.02
    WebP 13.3Mpx (L)      362  285  272  280  0.34     260   81   68   72  0.02
    WebP 13.3Mpx RGBA     365  287  275  280  2.64     265   85   74   72  0.03
    interactive: preview | crop
    PDF 40p 1-bit         159   90   75   80  0.05     159   93   75   80  0.07
    PDF 40p RGB JPEG      202  127  118  120  0.79     196  124  112  120  0.88
    PDF 3p RGB Flate      158   89   74   80  0.20     160   92   76   80  0.10
    PDF 3p RGB JPEG       173  105   89   88  0.34     177  109   93   96  0.41
    1-bit PNG 159Mpx      331  256  241  248  0.20     481  405  392  400  0.47
    1-bit TIFF 160Mpx     331  256  241  248  0.27     490  414  400  400  0.45
    L TIFF 160Mpx         464  390  374  376  0.57     463  387  374  376  0.60
    I;16 PNG 80Mpx        389  315  299  304  0.61     409  332  320  320  0.83
    I;16 TIFF 80Mpx       388  313  299  304  0.54     463  387  374  376  0.63
    RGB JPEG 40Mpx        180  104   91   96  0.17     379  301  289  296  1.46
    RGB PNG 34.8Mpx       360  285  270  272  0.36     335  258  246  248  0.33
    RGB PNG 39.7Mpx       387  314  298  304  0.45     359  282  269  272  0.37
    RGB TIFF 40Mpx        387  313  298  304  0.40     425  349  336  344  0.40
    LA PNG 40Mpx          314  239  224  224  0.36     360  284  271  272  0.32
    P PNG 40Mpx           351  277  261  264  0.32     249  172  159  160  0.23
    P BMP RLE 40Mpx       350  275  260  264  0.48     279  200  189  192  0.23
    RGBA PNG 30Mpx        390  315  301  304  0.45     310  233  220  224  0.26
    RGBA TIFF 30Mpx       388  313  299  304  0.47     388  310  299  304  0.31
    CMYK TIFF 30Mpx       387  313  298  304  0.46     387  311  298  304  0.32
    CMYK JPEG 30Mpx       179  105   89   88  0.12     311  235  222  224  0.26
    I TIFF 30Mpx          244  170  155  160  0.22     388  311  299  304  0.33
    F TIFF 30Mpx          244  170  155  160  0.22     387  310  298  304  0.34
    RGB16 PNG 20Mpx       332  258  242  248  0.37     260  183  170  176  0.23
    RGB16 TIFF 20Mpx      331  256  241  248  0.35     349  272  259  264  0.29
    RGBA16 PNG 15Mpx      333  258  243  248  0.41     235  157  146  152  0.20
    RGBA16 TIFF 15Mpx     331  256  241  248  0.42     330  253  240  248  0.28
    LA16 PNG 15Mpx        246  172  156  160  0.21     235  157  146  152  0.15
    WebP 13.3Mpx (L)       (MuPDF cannot open a WebP)     362  285  272  280  0.18
    WebP 13.3Mpx RGBA      (MuPDF cannot open a WebP)     366  289  276  280  0.77

Every path of a worker run in turn in ONE child (as in production, where
the allocator keeps some of what it freed) peaks higher: ``VmData`` 417 MiB
and ``VmPeak`` 507 MiB for extraction, 404 MiB and 494 MiB for preview and
crop. The worst single paths: extraction of the 40 Mpx LA PNG (412 MiB;
Pillow holds LA at four bytes a pixel and converts it), and the crop of a
160 Mpx 1-bit image (401 MiB).

The rule (owner decision, Task 11 review round 2): 1.5x headroom on what the
child allocates over its warm baseline (``VmData`` 66.7 MiB with the render
modules imported), ``RLIMIT_DATA = next64(baseline + 1.5 x (worst -
baseline))``, the worst being the largest ``VmData`` of the worker's paths,
fresh or in turn: extraction next64(66.7 + 1.5 x 350.4) = next64(592) = 640
MiB, interactive next64(66.7 + 1.5 x 337.5) = next64(573) = 576 MiB.
``RLIMIT_AS = max(next64(1.25 x the largest VmPeak), RLIMIT_DATA + 128
MiB)``: extraction max(640, 768) = 768 MiB, interactive max(640, 704) =
704 MiB. The ``+ 128 MiB`` term is a deviation from the plan, which had the
1.25 x term alone: ``VmSize`` runs ~84 MiB above ``VmData`` (libraries,
stack), so an address limit equal to the data limit would be the real
bound. Headroom over the worst path: extraction 1.64x on the growth (640 /
417 = 1.53x overall) and 768 / 507 = 1.52x address; interactive 1.51x on the
growth (576 / 404 = 1.43x overall) and 704 / 494 = 1.43x address. Re-run
under 640 / 768 and 576 / 704, every admitted path completed
(``last_outcome == "ok"``), fresh and in turn; the only failures are
MuPDF's, on a WebP preview, at any limit. Both rules are pinned by
``tests/test_sandbox.py::test_the_default_limits_follow_the_measured_growth_rule``.

The 2 GiB budget (owner decision S1), resident, every fixed part measured
(Task 11 re-review, 2026-10-04):

* the web process idle after start-up (``python -m lemely.web``, as the
  container runs it): 237.4 MB (226.4 MiB);
* the parent's growth while it holds the pages of the adversarial 40-page
  extraction (12.3 MB of PDF, every page one shared full-page noise image,
  scaled to the 160 Mpx scan cap: 466.0 MB of PNG): 500.5 MB (477.3 MiB);
* the equivalence parse worker's child: 71.9 MB (68.6 MiB);
* multiprocessing's ``resource_tracker``: 16.4 MB (15.6 MiB);
* the extraction worker's ``RLIMIT_DATA`` 640 MiB and the interactive
  worker's 576 MiB.

Together 2003.9 MiB of the instance's 2048: a margin of 44.1 MiB. The owner
accepted it, with the OOM priority as the backstop: every worker child sets
``oom_score_adj`` to 1000 (:data:`_OOM_SCORE_ADJ`), so if the instance runs
out the kernel kills a worker (one request gets a 422) before the web
server. Pinned at 40 MiB or more by
``tests/test_sandbox.py::test_the_default_limits_fit_the_two_gib_budget``.

The extraction timeout is 180 s (owner decision, Task 11 review), counting
any wait for the worker: the slowest extraction measured is 33 s, the
40-page JPEG PDF. The upload check's slowest run is 0.65 s, so it keeps
20 s.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import importlib.machinery
import logging
import multiprocessing
import os
import pickle
import re
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

from lemely.runtime.config import SandboxSettings, load_settings
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

_logger = logging.getLogger(__name__)

#: After a failed start, no new start is attempted for this long, as in
#: ``lemely.core.equivalence._ParseWorker``: where a child can never start
#: (from a daemonic process, say) each call would otherwise pay a spawn
#: attempt and log a warning. :meth:`ChildWorker.shutdown` clears it.
_START_COOLDOWN_SECONDS = 30.0

#: How long :meth:`ChildWorker.shutdown` waits for a call in flight before it
#: kills the child under it. A stream kept alive and suspended (by a
#: traceback that holds its frame, say) holds the lock indefinitely.
_SHUTDOWN_LOCK_WAIT_SECONDS = 5.0

#: The only modules a target may come from. Target names are code constants,
#: but the child imports and calls whatever it is told; this keeps a mistaken
#: or injected name from reaching the standard library or a dependency.
_TARGET_PACKAGE = "lemely"

#: Further modules allowed to provide targets. Empty in production; the test
#: fixtures (``tests/sandbox_fixtures.py``) add ``tests.sandbox_targets`` with
#: monkeypatch. A child gets the value in force when it is started.
_EXTRA_TARGET_MODULES: frozenset[str] = frozenset()

#: The limits a child sets, in the order its ready message reports them:
#: ``RLIMIT_DATA``, ``RLIMIT_AS``, ``RLIMIT_CORE`` (0: a crashing decoder
#: must not write a core file full of a user's scan) and its OOM priority
#: (:data:`_OOM_SCORE_ADJ`).
_LIMIT_NAMES = ("RLIMIT_DATA", "RLIMIT_AS", "RLIMIT_CORE", "oom_score_adj")

#: The child's ``/proc/self/oom_score_adj``: 1000, the most, so when the
#: instance runs out of memory the kernel kills a worker child (that request
#: gets a 422; the next call respawns it) before the web server. Owner
#: decision, Task 11 re-review: the 2 GiB budget's measured margin is ~44 MiB.
#: Raising one's own score needs no privilege; a kernel or container that
#: forbids the write leaves the inherited score, and the parent warns.
_OOM_SCORE_ADJ = 1000

#: The text MuPDF's allocator throws with when ``malloc`` fails
#: (``fz_malloc``, ``fz_calloc``, ``fz_realloc``: ``"malloc (119076300
#: bytes) failed"``). MuPDF has no memory error class: these arrive as
#: ``FzErrorSystem`` (``FZ_ERROR_SYSTEM``), the class that also carries I/O
#: failures, so the class alone does not say "memory". A size computation
#: that overflows (``"calloc (N x M bytes) failed (overflow)"``, and the
#: ``malloc array``/``realloc array`` forms, which exist only as overflows)
#: is a malformed request, not memory running out, so it is excluded. The
#: texts are MuPDF 1.29's (``strings libmupdf.so.29.0``).
_MUPDF_ALLOCATION_FAILED = re.compile(
    r"\b(?:malloc|calloc|realloc) \([^)]*\) failed(?! \(overflow\))"
)

#: The ``PdfiumError`` pypdfium2 raises for a bitmap pdfium could not
#: allocate. Unreachable with pypdfium2's default (native) bitmaps, whose
#: buffer is a ctypes allocation that fails as a Python ``MemoryError``;
#: kept so a switch to a pdfium-allocated bitmap is still read as memory.
_PDFIUM_BITMAP_FAILED = "Failed to get bitmap buffer"

#: The pipe protocol. Parent to child: ``("call" | "stream", target, args)``,
#: or ``None`` to stop. Child to parent: ``(kind, value)``, see `_child_main`.
type _Request = tuple[str, str, tuple[object, ...]] | None
type _Reply = tuple[str, object]


class SandboxFailure(LemelyError):
    """A sandboxed call that produced no result; ``reason`` says which way.

    ``str()`` is the message alone. ``reason`` (``"timeout"``, ``"memory"``,
    ``"crash"``, ``"unavailable"`` or ``"error"``) is for logs and for the
    caller's choice of response. Both go to ``args``, so the error pickles.
    """

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message, reason)
        self.reason = reason

    def __str__(self) -> str:
        """The message alone; ``reason`` stays in ``args``."""
        return str(self.args[0])


class SandboxTimeout(SandboxFailure):
    """The child gave no answer within the call's timeout; it was killed."""


class SandboxMemory(SandboxFailure):
    """The target ran out of memory under the child's limits; the child lives on."""


class SandboxCrash(SandboxFailure):
    """The child exited, broke the pipe, or sent a reply that cannot be read."""


class SandboxUnavailable(SandboxFailure):
    """No child could serve the call: it is busy, or it could not be started."""


class SandboxError(SandboxFailure):
    """The target raised something other than a ``LemelyError``.

    The message is that exception's ``repr``: for logs, never for a client.
    """


@functools.cache
def sandbox_settings() -> SandboxSettings:
    """The sandbox settings, read once per process.

    ``load_settings`` reads TOML and the environment, so it must not run per
    request. Call this through the module (``sandbox.sandbox_settings()``),
    never through a ``from`` import, so a test that patches the module
    attribute changes what every caller sees. Logs ``sandbox_disabled`` once,
    when the settings load with the sandbox off: every scan then decodes in
    the web process, unbounded.
    """
    settings = load_settings().sandbox
    if not settings.enabled:
        _logger.warning(
            "sandbox_disabled: scan rendering runs in the web process, "
            "with no memory limit and no timeout (LEMELY_SANDBOX__ENABLED=false)"
        )
    return settings


class _Target(Protocol):
    def __call__(self, *args: object) -> object: ...


def _is_allowed_module(name: str) -> bool:
    return (
        name == _TARGET_PACKAGE
        or name.startswith(f"{_TARGET_PACKAGE}.")
        or name in _EXTRA_TARGET_MODULES
    )


def _resolve(target: str) -> _Target:
    """The function named by the dotted path ``target``, imported now.

    ``ValueError`` unless both the path and the function it names belong to
    ``lemely`` (or :data:`_EXTRA_TARGET_MODULES`): the second check stops a
    ``lemely`` module's import of someone else's function (``os.system``,
    say) from being reached through that module.
    """
    module_name, _, attribute = target.rpartition(".")
    if not _is_allowed_module(module_name):
        raise ValueError(f"sandbox target {target!r} is not lemely code")
    function = getattr(importlib.import_module(module_name), attribute)
    if not callable(function):
        raise TypeError(f"{target} is not callable")
    defined_in = getattr(function, "__module__", None)
    if not (isinstance(defined_in, str) and _is_allowed_module(defined_in)):
        raise ValueError(f"sandbox target {target!r} is not lemely code (from {defined_in!r})")
    return cast("_Target", function)


def _is_allocation_failure(exc: BaseException) -> bool:
    """Whether ``exc`` is a C library's report that an allocation failed.

    Matched by class name, so this module imports neither library: MuPDF's
    ``FzErrorSystem`` carrying its allocator's text
    (:data:`_MUPDF_ALLOCATION_FAILED`), or pypdfium2's ``PdfiumError`` for a
    bitmap it could not get (:data:`_PDFIUM_BITMAP_FAILED`). Both class and
    text must match: the same classes also report I/O and format failures.
    """
    classes = {(cls.__module__, cls.__qualname__) for cls in type(exc).__mro__}
    try:
        if ("pymupdf.mupdf", "FzErrorSystem") in classes:
            return _MUPDF_ALLOCATION_FAILED.search(str(exc)) is not None
        if ("pypdfium2._helpers.misc", "PdfiumError") in classes:
            return str(exc).startswith(_PDFIUM_BITMAP_FAILED)
    except Exception:  # an exception whose str() fails: not ours to read, an error
        return False
    return False


def _memory_detail(exc: BaseException) -> str | None:  # pragma: no cover - runs in the child
    """``str(exc)`` for the logs (MuPDF's names the allocation's size), or ``None``."""
    try:
        return str(exc) or None
    except Exception:  # a C exception whose text cannot be read
        return None


def _apply_limits(  # pragma: no cover - runs in the child
    data_limit: int, address_limit: int
) -> tuple[int, ...] | None:
    """Set ``RLIMIT_DATA``, ``RLIMIT_AS``, ``RLIMIT_CORE`` (to 0) and the OOM priority, each alone.

    Returns the soft limits now in force and the ``oom_score_adj`` read back
    (:func:`_apply_oom_priority`), in :data:`_LIMIT_NAMES` order, for the
    ready message; ``None`` without a ``resource`` module. A limit that
    cannot be set is left as it was (the parent sees the difference and
    warns), and a hard limit already below the request is kept, never raised.
    """
    try:
        import resource
    except ImportError:  # not Unix
        return None
    requests = (
        (resource.RLIMIT_DATA, data_limit),
        (resource.RLIMIT_AS, address_limit),
        (resource.RLIMIT_CORE, 0),
    )
    applied: list[int] = []
    for which, limit in requests:
        try:
            _soft, hard = resource.getrlimit(which)
            soft = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
            resource.setrlimit(which, (soft, hard))
        except (ValueError, OSError):  # a refused limit: reported as it stands
            pass
        applied.append(resource.getrlimit(which)[0])
    applied.append(_apply_oom_priority())
    return tuple(applied)


def _apply_oom_priority() -> int:  # pragma: no cover - runs in the child
    """Write :data:`_OOM_SCORE_ADJ` to ``/proc/self/oom_score_adj``; return what it reads.

    Guarded: some kernels and containers forbid the write, and a system
    without ``/proc`` has no such file. Either way the score in force is
    reported (0, the default, where it cannot be read).
    """
    path = "/proc/self/oom_score_adj"
    with contextlib.suppress(OSError), open(path, "w", encoding="ascii") as adj:
        adj.write(str(_OOM_SCORE_ADJ))
    try:
        with open(path, encoding="ascii") as adj:
            return int(adj.read().strip())
    except (OSError, ValueError):
        return 0


class _PipeClosedError(Exception):
    """The parent's end of the pipe is gone; the child stops."""


def _send(  # pragma: no cover - runs in the child
    conn: Connection[_Reply, _Request], kind: str, value: object
) -> None:
    """Send ``(kind, value)``, or ``("error", repr)`` if it cannot be pickled.

    The reply is pickled here, before anything is written, so a value that
    does not pickle never leaves half a message in the pipe. A rejection is
    also loaded back once: an exception whose ``__init__`` cannot be rebuilt
    from its ``args`` pickles fine but would fail in the parent, which would
    then read a healthy child as crashed.
    """
    try:
        data = pickle.dumps((kind, value), protocol=pickle.HIGHEST_PROTOCOL)
        if kind == "rejected":
            pickle.loads(data)  # noqa: S301 - our own bytes, from the line above
    except MemoryError:
        raise
    except Exception as exc:
        unsendable = value if kind == "rejected" else exc
        data = pickle.dumps(("error", repr(unsendable)), protocol=pickle.HIGHEST_PROTOCOL)
    try:
        conn.send_bytes(data)
    except (EOFError, OSError) as exc:
        raise _PipeClosedError from exc


def _serve(  # pragma: no cover - runs in the child
    conn: Connection[_Reply, _Request], mode: str, target: str, args: tuple[object, ...]
) -> None:
    """Run one request and send its reply (or, for a stream, its replies)."""
    try:
        result = _resolve(target)(*args)
        if mode == "stream":
            for item in cast("Iterable[object]", result):
                _send(conn, "item", item)
                # Sent: let it go before the iterator makes the next one, so
                # the child never holds a sent item through the next.
                del item
            result = None
        _send(conn, "ok", result)
    except _PipeClosedError:
        raise
    except MemoryError as exc:
        _send(conn, "memory", _memory_detail(exc))
    except LemelyError as exc:
        _send(conn, "rejected", exc)
    except Exception as exc:
        if _is_allocation_failure(exc):
            _send(conn, "memory", _memory_detail(exc))
        else:
            _send(conn, "error", repr(exc))


def _child_main(  # pragma: no cover - runs in the child
    conn: Connection[_Reply, _Request],
    data_limit: int,
    address_limit: int,
    extra_target_modules: frozenset[str] = frozenset(),
) -> None:
    """The worker's loop, run in the ``spawn``ed child (hence no coverage).

    ``extra_target_modules`` is the parent's :data:`_EXTRA_TARGET_MODULES`
    at start: the child imports this module afresh, so a patch in the parent
    reaches it only this way.

    Sets the limits and the OOM priority, sends ``("ready", applied)`` (the
    soft limits and ``oom_score_adj`` now in force, see
    :func:`_apply_limits`), then per request replies
    ``("ok", value)``; for a stream, ``("item", value)`` per element first
    and then ``("ok", None)``; ``("rejected", exc)`` for a ``LemelyError``
    (the instance itself), ``("memory", detail)`` for a ``MemoryError`` or a C
    library's allocation failure (:func:`_is_allocation_failure`; ``detail``
    is the failure's own text, which names the allocation's size, or
    ``None`` when it has none) and
    ``("error", repr(exc))`` for any other exception. ``None`` ends the loop,
    as does a closed pipe (the parent exited or was killed).

    SIGINT is ignored: a Ctrl-C in the terminal reaches the whole process
    group, and the child's lifetime belongs to the parent.
    """
    global _EXTRA_TARGET_MODULES  # this child's own copy, set once at start
    _EXTRA_TARGET_MODULES = extra_target_modules
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    applied = _apply_limits(data_limit, address_limit)
    try:
        conn.send(("ready", applied))
        while True:
            request = conn.recv()
            if request is None:
                return
            mode, target, args = request
            _serve(conn, mode, target, args)
    except (EOFError, OSError, _PipeClosedError):
        return


#: Held while ``__main__.__spec__`` is swapped for a child's start
#: (:func:`_start_without_parent_main`): two workers starting at once would
#: otherwise save each other's stand-in and leave it in place. Also held
#: across an ``os.fork`` (the ``register_at_fork`` call at the end of this
#: module), so a forked process never inherits the stand-in or a held lock.
#: ``spawn`` starts its child with ``fork_exec``, which runs no fork hooks,
#: so a start under the lock cannot deadlock on it.
_MAIN_SWAP_LOCK = threading.Lock()

#: What ``spawn`` is shown as ``__main__``'s spec while a child starts.
#: CPython's ``multiprocessing.spawn`` re-runs the parent's main module in the
#: child (``_fixup_main_from_path``, ``_fixup_main_from_name``) unless that
#: module is named ``"__main__"`` or ends in ``".__main__"``, which it leaves
#: alone. ``python -m lemely.web`` (the container) already has such a name.
_UNRUN_MAIN_SPEC = importlib.machinery.ModuleSpec("__main__", None)


def _start_without_parent_main(process: BaseProcess) -> None:
    """``process.start()``, with the child told to leave its ``__main__`` alone.

    ``spawn`` reads ``sys.modules["__main__"].__spec__`` (and, when that is
    ``None``, ``__file__``) inside ``start()`` to decide what the child
    re-runs before it unpickles its target. For the start the spec is
    :data:`_UNRUN_MAIN_SPEC`, so the child runs only :func:`_child_main` and
    the modules its targets import. The parent's own spec (``None`` for a
    path-run script) is put back as soon as ``start()`` returns, under
    :data:`_MAIN_SWAP_LOCK`. Nothing a child is given lives in
    ``__main__``: targets are dotted paths into importable modules.
    """
    main = sys.modules.get("__main__")
    if main is None:  # an embedding with no main module: nothing to re-run
        process.start()
        return
    with _MAIN_SWAP_LOCK:
        had_spec = "__spec__" in vars(main)
        saved = main.__spec__ if had_spec else None
        main.__spec__ = _UNRUN_MAIN_SPEC
        try:
            process.start()
        finally:
            if had_spec:
                main.__spec__ = saved
            else:
                del main.__spec__


class ChildWorker:
    """One reusable, killable, rlimit-bounded child process.

    Modelled on ``lemely.core.equivalence._ParseWorker``. ``spawn``, never
    ``fork``: the web server runs sync routes on threads. The child is a
    daemon, so ``multiprocessing``'s atexit hook ends it with the parent.
    Calls are serialised by a lock, and the time spent waiting for it counts
    against the caller's ``timeout``: a call that cannot get the worker in
    time is refused with :class:`SandboxUnavailable` (``"busy"``) instead of
    queueing past its deadline. The time to (re)start a child is not counted,
    so a cold start on a slow host is never mistaken for a runaway target; it
    has its own bound, ``start_timeout_seconds``. The owner pid is recorded
    and :meth:`_forget_after_fork` resets the lock and forgets the child in
    a forked process.

    With ``sandbox_settings().enabled`` false, :meth:`call` and :meth:`stream`
    run the target in the calling process and its exceptions propagate
    unchanged; this is for tests that patch a library in the test process.

    :attr:`last_outcome` records how the most recent call ended, on any
    thread, for tests: ``"ok"``, ``"rejected"``, ``"memory"``, ``"crash"``,
    ``"timeout"``, ``"error"``, ``"unavailable"`` (no child could be
    started), ``"busy"`` (the lock wait outlived the timeout) or
    ``"interrupted"`` (an interrupt, or a stream closed early, killed it).
    """

    def __init__(self, name: str, *, limits: Callable[[SandboxSettings], tuple[int, int]]) -> None:
        self.name = name
        #: ``(RLIMIT_DATA, RLIMIT_AS)`` for a child started under the settings.
        self._limits = limits
        self._lock = threading.Lock()
        self._process: BaseProcess | None = None
        self._conn: Connection[_Request, _Reply] | None = None
        self._owner_pid: int | None = None
        #: `time.monotonic()` of the last failed start, for the cool-down.
        self._start_failed_at: float | None = None
        self.last_outcome: str | None = None
        #: The soft ``(RLIMIT_DATA, RLIMIT_AS, RLIMIT_CORE)`` and the
        #: ``oom_score_adj`` the current child reported at start (``None``
        #: before a start, or where it could not read them). Differs from what
        #: was asked for only after a warning.
        self.applied_limits: tuple[int, ...] | None = None

    def _forget_after_fork(self) -> None:
        """In a forked child: the parent's worker, pipe and lock are not ours."""
        self._lock = threading.Lock()
        self._process = self._conn = self._owner_pid = None
        self._start_failed_at = None

    # -- the child's lifecycle ------------------------------------------------

    def _start(self) -> bool:
        """Start a child, or ``False``; inside the cool-down, without trying."""
        failed_at = self._start_failed_at
        if failed_at is not None and time.monotonic() - failed_at < _START_COOLDOWN_SECONDS:
            return False
        started = self._spawn()
        self._start_failed_at = None if started else time.monotonic()
        return started

    def _spawn(self) -> bool:
        settings = sandbox_settings()
        data_limit, address_limit = self._limits(settings)
        context = multiprocessing.get_context("spawn")
        try:
            parent_conn, child_conn = context.Pipe()
        except OSError:  # out of file descriptors
            _logger.warning("%s not started: no pipe", self.name, exc_info=True)
            return False
        process = context.Process(
            target=_child_main,
            args=(child_conn, data_limit, address_limit, _EXTRA_TARGET_MODULES),
            name=self.name,
            daemon=True,
        )
        try:
            _start_without_parent_main(process)
        except BaseException as exc:  # a daemonic parent, out of fds -- or an interrupt
            parent_conn.close()
            child_conn.close()
            if process.pid is not None:  # spawned before the failure: never leave it running
                process.kill()
                process.join()
            if not isinstance(exc, Exception):
                raise
            _logger.warning("%s not started", self.name, exc_info=True)
            return False
        child_conn.close()
        self._process, self._conn, self._owner_pid = process, parent_conn, os.getpid()
        reply: object = None
        try:
            if parent_conn.poll(settings.start_timeout_seconds):
                reply = parent_conn.recv()
        except (EOFError, OSError):
            reply = None
        except BaseException:  # interrupted mid-handshake: an unread "ready" would desync
            self._discard(kill=True)
            raise
        if not (isinstance(reply, tuple) and len(reply) == 2 and reply[0] == "ready"):
            _logger.warning("%s did not report ready", self.name)
            self._discard(kill=True)
            return False
        self._check_limits((data_limit, address_limit, 0, _OOM_SCORE_ADJ), reply[1])
        return True

    def _check_limits(self, requested: tuple[int, ...], applied: object) -> None:
        """Record the limits the child reported, and warn where they fall short."""
        if not (isinstance(applied, tuple) and len(applied) == len(requested)):
            self.applied_limits = None
            _logger.warning("%s started without memory limits (no resource module)", self.name)
            return
        self.applied_limits = tuple(int(value) for value in applied)
        for name, asked, got in zip(_LIMIT_NAMES, requested, self.applied_limits, strict=True):
            if got != asked:
                _logger.warning(
                    "%s runs with %s=%d, not the %d asked for (refused, or a lower hard limit)",
                    self.name,
                    name,
                    got,
                    asked,
                )

    def _discard(self, *, kill: bool) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = self._owner_pid = None
        self.applied_limits = None
        if conn is not None:
            conn.close()
        if process is None:
            return
        if kill:
            process.kill()
        process.join()
        process.close()

    def _ready(self) -> Connection[_Request, _Reply] | None:
        """The live child's pipe, starting a child if needed; ``None`` if none starts."""
        if self._process is None or self._owner_pid != os.getpid():
            # A foreign or never-started worker: never joined here.
            self._process = self._conn = None
            return self._conn if self._start() else None
        if not self._process.is_alive():
            self._discard(kill=False)
            return self._conn if self._start() else None
        return self._conn

    # -- one call ---------------------------------------------------------------

    def _enter(
        self, target: str, args: tuple[object, ...], *, mode: str, timeout: float
    ) -> tuple[Connection[_Request, _Reply], float]:
        """Take the lock, make sure a child is up, send the request.

        Returns the pipe and the deadline (``time.monotonic()``) for the
        replies; the caller releases the lock. Raises
        :class:`SandboxUnavailable` (lock released) when the lock wait uses
        up ``timeout`` or no child starts.
        """
        entered = time.monotonic()
        if not self._lock.acquire(timeout=max(timeout, 0.0)):
            self.last_outcome = "busy"
            raise SandboxUnavailable("busy", "unavailable")
        try:
            remaining = timeout - (time.monotonic() - entered)
            if remaining <= 0:
                self.last_outcome = "busy"
                raise SandboxUnavailable("busy", "unavailable")
            conn = self._ready()
            if conn is None:
                self.last_outcome = "unavailable"
                raise SandboxUnavailable(f"{self.name} could not be started", "unavailable")
            try:
                request = pickle.dumps((mode, target, args), protocol=pickle.HIGHEST_PROTOCOL)
            except Exception as exc:  # an argument that does not pickle: the child is untouched
                self.last_outcome = "error"
                raise SandboxError(repr(exc), "error") from exc
            deadline = time.monotonic() + remaining
            self._exchange(lambda: conn.send_bytes(request))
        except BaseException:
            self._lock.release()
            raise
        return conn, deadline

    def _exchange[R](self, operation: Callable[[], R]) -> R:
        """Run one pipe operation; a broken pipe or an interrupt kills the child."""
        try:
            return operation()
        except Exception as exc:  # EOFError/OSError on a crash, or an unpicklable reply
            self._discard(kill=True)
            self.last_outcome = "crash"
            raise SandboxCrash(f"{self.name} exited or sent an unreadable reply", "crash") from exc
        except BaseException:
            # KeyboardInterrupt/SystemExit while a reply is outstanding: a live
            # child would hand this call's reply to the next caller.
            self._discard(kill=True)
            self.last_outcome = "interrupted"
            raise

    def _receive(
        self, conn: Connection[_Request, _Reply], deadline: float, timeout: float
    ) -> _Reply:
        """The next reply, or :class:`SandboxTimeout` (child killed) at ``deadline``."""
        if not self._exchange(lambda: conn.poll(max(deadline - time.monotonic(), 0.0))):
            self._discard(kill=True)
            self.last_outcome = "timeout"
            raise SandboxTimeout(f"{self.name} gave no answer within {timeout:g} s", "timeout")
        reply: object = self._exchange(conn.recv)
        if not (isinstance(reply, tuple) and len(reply) == 2 and isinstance(reply[0], str)):
            self._discard(kill=True)
            self.last_outcome = "crash"
            raise SandboxCrash(f"{self.name} broke the reply protocol", "crash")
        return cast("_Reply", reply)

    def _raise_failure(self, kind: str, value: object) -> NoReturn:
        """Raise what a ``rejected``/``memory``/``error`` reply stands for."""
        if kind == "rejected" and isinstance(value, LemelyError):
            self.last_outcome = "rejected"
            raise value
        if kind == "memory":
            self.last_outcome = "memory"
            # The detail (MuPDF's "malloc (N bytes) failed") goes to the logs
            # with the message; no route shows a SandboxFailure's text to a client.
            detail = f": {value}" if isinstance(value, str) and value else ""
            raise SandboxMemory(f"{self.name} ran out of memory{detail}", "memory")
        if kind == "error":
            self.last_outcome = "error"
            raise SandboxError(str(value), "error")
        self._discard(kill=True)
        self.last_outcome = "crash"
        raise SandboxCrash(f"{self.name} sent an unexpected {kind!r} reply", "crash")

    def _wrong_type(self, target: str, value: object, expected: type) -> SandboxError:
        self.last_outcome = "error"
        return SandboxError(
            f"{target} returned {type(value).__name__}, not {expected.__name__}", "error"
        )

    def call[T](self, target: str, *args: object, timeout: float, result_type: type[T]) -> T:
        """``target(*args)`` run in the child, within ``timeout`` seconds of entry.

        Raises the target's ``LemelyError`` as it was raised, or a
        :class:`SandboxFailure`: :class:`SandboxTimeout`,
        :class:`SandboxMemory`, :class:`SandboxCrash`,
        :class:`SandboxUnavailable` or :class:`SandboxError` (including a
        result that is not a ``result_type``).
        """
        if not sandbox_settings().enabled:
            value = _resolve(target)(*args)
            if not isinstance(value, result_type):
                raise self._wrong_type(target, value, result_type)
            return value
        conn, deadline = self._enter(target, args, mode="call", timeout=timeout)
        try:
            kind, value = self._receive(conn, deadline, timeout)
            if kind != "ok":
                self._raise_failure(kind, value)
            if not isinstance(value, result_type):
                raise self._wrong_type(target, value, result_type)
            self.last_outcome = "ok"
            return value
        finally:
            self._lock.release()

    def stream[T](
        self, target: str, *args: object, timeout: float, item_type: type[T]
    ) -> Iterator[T]:
        """The items of the iterator ``target(*args)`` returns, made in the child.

        ``timeout`` is one deadline, from the first ``next()``, for the lock
        wait plus the whole iteration; the worker stays locked until the last
        item. Closing the generator early (or any exception thrown into it)
        kills the child, which may still be producing, and the next call
        respawns it. Failures are raised as by :meth:`call`, after any items
        already yielded.
        """
        if not sandbox_settings().enabled:
            for item in cast("Iterable[object]", _resolve(target)(*args)):
                if not isinstance(item, item_type):
                    raise self._wrong_type(target, item, item_type)
                yield item
            return
        conn, deadline = self._enter(target, args, mode="stream", timeout=timeout)
        try:
            while True:
                kind, value = self._receive(conn, deadline, timeout)
                if kind == "ok":
                    self.last_outcome = "ok"
                    return
                if kind != "item":
                    self._raise_failure(kind, value)
                if not isinstance(value, item_type):
                    self._discard(kill=True)  # mid-stream: its other items are still coming
                    raise self._wrong_type(target, value, item_type)
                try:
                    yield value
                except BaseException:
                    self._discard(kill=True)
                    self.last_outcome = "interrupted"
                    raise
        finally:
            self._lock.release()

    # -- inspection and shutdown ----------------------------------------------

    def pid(self) -> int | None:
        """The live child's pid; ``None`` when there is none, or it has died."""
        process = self._process
        if process is None or self._owner_pid != os.getpid():
            return None
        try:
            return process.pid if process.is_alive() else None
        except ValueError:  # closed by another thread in the meantime
            return None

    def shutdown(self) -> None:
        """Stop and join the child, and clear the start cool-down.

        Waits at most :data:`_SHUTDOWN_LOCK_WAIT_SECONDS` for a call in
        flight. Past that (a suspended stream kept alive holds the lock for
        as long as it lives) the child is killed without touching the state
        the holder owns; the holder's next pipe operation then fails as a
        :class:`SandboxCrash` and discards it. Not an ``RLock``: a stream may
        be resumed, and so release the lock, on another thread.
        """
        if not self._lock.acquire(timeout=_SHUTDOWN_LOCK_WAIT_SECONDS):
            self._start_failed_at = None
            process = self._process
            if process is not None and self._owner_pid == os.getpid():
                with contextlib.suppress(ValueError, OSError):  # closed or gone meanwhile
                    process.kill()
            _logger.warning(
                "%s was busy for %g s at shutdown; its child was killed",
                self.name,
                _SHUTDOWN_LOCK_WAIT_SECONDS,
            )
            return
        try:
            self._start_failed_at = None
            if self._owner_pid is not None and self._owner_pid != os.getpid():
                # Another process's child (no fork hook on this platform): not
                # ours to signal or join. The lock is NOT replaced here -- a
                # thread may be waiting on it.
                self._process = self._conn = self._owner_pid = None
                return
            if self._conn is not None:
                with contextlib.suppress(OSError):
                    self._conn.send(None)
            self._discard(kill=True)
        finally:
            self._lock.release()


#: Extraction and the upload check.
EXTRACTION_WORKER = ChildWorker(
    "lemely-extraction-worker",
    limits=lambda s: (s.extraction_data_limit_bytes, s.extraction_address_limit_bytes),
)
#: Preview and crop.
INTERACTIVE_WORKER = ChildWorker(
    "lemely-interactive-worker",
    limits=lambda s: (s.interactive_data_limit_bytes, s.interactive_address_limit_bytes),
)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_MAIN_SWAP_LOCK.acquire,
        after_in_parent=_MAIN_SWAP_LOCK.release,
        after_in_child=_MAIN_SWAP_LOCK.release,
    )
    os.register_at_fork(after_in_child=EXTRACTION_WORKER._forget_after_fork)
    os.register_at_fork(after_in_child=INTERACTIVE_WORKER._forget_after_fork)
