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
  ``MemoryError`` in the child is reported and the child lives on; an
  allocation failure inside a C library may instead arrive as that library's
  own exception (pypdfium2 5.11 raises ``PdfiumError``, a ``RuntimeError``;
  pymupdf has no memory error class), or as an abort that ends the child.
  Callers therefore treat every :class:`SandboxFailure` alike.
* A call that outlives its timeout kills the child; the next call respawns it.
* A :class:`~lemely.runtime.errors.LemelyError` raised by the target (a scan
  refusal) crosses the pipe intact, pickled with its ``args``, and is raised
  again in the caller. Any other exception becomes a :class:`SandboxError`
  carrying its ``repr``, for the logs only.

Two module workers split the work so a long extraction never blocks an
interactive request: :data:`EXTRACTION_WORKER` (extraction and the upload
check) and :data:`INTERACTIVE_WORKER` (preview and crop). Their limits and
timeouts are :class:`~lemely.runtime.config.SandboxSettings`, read once per
process through :func:`sandbox_settings`.

``lemely.runtime`` may not import ``lemely.io``, ``lemely.core`` or
``lemely.app`` (import-linter), so a target is named by dotted path
(``"lemely.io.rasterise.rasterise_pdf_to_pages"``) and imported in the child
when first called, and the child sorts exceptions by ``LemelyError`` alone.
Target names are fixed strings in the calling code, never user input.

Measured in this venv (Linux, CPython 3.13, 2026-10-01): a cold start, from
``spawn`` to ``("ready", None)``, takes 0.16-0.18 s; a warm round trip to a
trivial target about 0.02 ms. At ready the child is about 41 MB resident,
``VmData`` 26 MB and ``VmSize`` 65 MB, so what it imports before its limits
apply sits well inside even the interactive worker's 192 MiB ``RLIMIT_DATA``
and 448 MiB ``RLIMIT_AS``. The limits themselves are the starting points of
the 2 GiB memory budget (owner decision S1), to be replaced by the measured
peak of each render path inside the child.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import logging
import multiprocessing
import os
import pickle
import signal
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
    attribute changes what every caller sees.
    """
    return load_settings().sandbox


class _Target(Protocol):
    def __call__(self, *args: object) -> object: ...


def _resolve(target: str) -> _Target:
    """The function named by the dotted path ``target``, imported now."""
    module_name, _, attribute = target.rpartition(".")
    function = getattr(importlib.import_module(module_name), attribute)
    if not callable(function):
        raise TypeError(f"{target} is not callable")
    return cast("_Target", function)


def _apply_limits(  # pragma: no cover - runs in the child
    data_limit: int, address_limit: int
) -> None:
    """Lower ``RLIMIT_DATA`` and ``RLIMIT_AS``; each one independently.

    A limit that cannot be set (no ``resource`` module, or a refusal) is left
    as it was, and the caller's timeout remains the only bound on it. A hard
    limit already below the request is kept, never raised.
    """
    try:
        import resource
    except ImportError:  # not Unix
        return
    for which, limit in ((resource.RLIMIT_DATA, data_limit), (resource.RLIMIT_AS, address_limit)):
        try:
            _soft, hard = resource.getrlimit(which)
            soft = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
            resource.setrlimit(which, (soft, hard))
        except (ValueError, OSError):  # a refused limit
            continue


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
            result = None
        _send(conn, "ok", result)
    except _PipeClosedError:
        raise
    except MemoryError:
        _send(conn, "memory", None)
    except LemelyError as exc:
        _send(conn, "rejected", exc)
    except Exception as exc:
        _send(conn, "error", repr(exc))


def _child_main(  # pragma: no cover - runs in the child
    conn: Connection[_Reply, _Request], data_limit: int, address_limit: int
) -> None:
    """The worker's loop, run in the ``spawn``ed child (hence no coverage).

    Sets both limits, sends ``("ready", None)``, then per request replies
    ``("ok", value)``; for a stream, ``("item", value)`` per element first
    and then ``("ok", None)``; ``("rejected", exc)`` for a ``LemelyError``
    (the instance itself), ``("memory", None)`` for a ``MemoryError`` and
    ``("error", repr(exc))`` for any other exception. ``None`` ends the loop,
    as does a closed pipe (the parent exited or was killed).

    SIGINT is ignored: a Ctrl-C in the terminal reaches the whole process
    group, and the child's lifetime belongs to the parent.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _apply_limits(data_limit, address_limit)
    try:
        conn.send(("ready", None))
        while True:
            request = conn.recv()
            if request is None:
                return
            mode, target, args = request
            _serve(conn, mode, target, args)
    except (EOFError, OSError, _PipeClosedError):
        return


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
            args=(child_conn, data_limit, address_limit),
            name=self.name,
            daemon=True,
        )
        try:
            process.start()
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
        try:
            ready = parent_conn.poll(settings.start_timeout_seconds)
            ready = ready and parent_conn.recv() == ("ready", None)
        except (EOFError, OSError):
            ready = False
        except BaseException:  # interrupted mid-handshake: an unread "ready" would desync
            self._discard(kill=True)
            raise
        if not ready:
            _logger.warning("%s did not report ready", self.name)
            self._discard(kill=True)
        return ready

    def _discard(self, *, kill: bool) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = self._owner_pid = None
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
            raise SandboxMemory(f"{self.name} ran out of memory", "memory")
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
        process = self._process
        return None if process is None else process.pid

    def shutdown(self) -> None:
        """Stop and join the child, and clear the start cool-down."""
        with self._lock:
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
    os.register_at_fork(after_in_child=EXTRACTION_WORKER._forget_after_fork)
    os.register_at_fork(after_in_child=INTERACTIVE_WORKER._forget_after_fork)
