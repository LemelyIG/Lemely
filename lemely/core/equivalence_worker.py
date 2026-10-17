"""The parse worker behind :mod:`lemely.core.equivalence` (#271).

One reusable, killable child process for all of the parse's SymPy work, the
pipe protocol it speaks, and the structural bounds it enforces on every power
(see :class:`_ParseWorker`). Split out of the facade so the spawned child
imports this module and :mod:`lemely.core.equivalence_tables` only, never the
normalisation passes. Imports the tables, never the facade.
"""

from __future__ import annotations

import contextlib
import logging
import math
import multiprocessing
import os
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING, cast

import sympy

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess
from sympy.parsing.sympy_parser import parse_expr

from lemely.core.equivalence_tables import _TRANSFORMATIONS, _UNIT_LOCAL_DICT
from lemely.runtime.process_start import start_without_parent_main

# Spelled out, not `__name__`: the facade's logger name is what log filters and
# `caplog.at_level(..., logger=eq.__name__)` match, and the worker's "parse
# worker not started" warnings must keep it.
_logger = logging.getLogger("lemely.core.equivalence")

#: A caret/`**` tower (`9^9^9`) or a single huge literal exponent
#: (`2**100000000`) has no realistic CAIE reading and can otherwise hang
#: parsing or produce a multi-million-digit integer (I8 review MUST-FIX #9).
_MAX_EXPONENT_VALUE = 1000

#: The longest exact number a parse may RETURN (review round 1 of triage F2).
#: `str()`/`srepr()` of a longer int raises ValueError under CPython's
#: int-to-string limit (`sys.get_int_max_str_digits()`, default 4300 digits),
#: and `equivalent` prints both sides -- so `(10^300+1)^1000*(10^300+3)^1000`,
#: each power within bounds, returned a 1,993,157-bit Integer and then raised
#: straight through `correction_ai`. Never above the default (the caller may
#: not share this process's setting); lower if this process lowered it.
_MAX_RESULT_DIGITS = min(sys.get_int_max_str_digits() or 4300, 4300)
#: ...in bits: any int of at most this many bits has at most that many digits.
_MAX_RESULT_INT_BITS = int((_MAX_RESULT_DIGITS - 1) / math.log10(2))

#: Triage F2 (2026-09-29): the exponent regexes read literals, so a COMPUTED
#: exponent (`2^(999*999*999)`, `2^(999!)`) slipped past them and SymPy then
#: built the integer -- 997,003,000 bits in 3.8 s with the GIL held, so the
#: whole process froze and `_run_bounded`'s timeout was moot. The structural
#: bound in `_pow_would_explode` refuses any power whose RESULT would exceed
#: this many bits, on top of the per-exponent literal cap above. It was
#: 1,000,000 until review round 1: a power the result bound above would
#: refuse anyway is not worth computing first, so the two now agree
#: (14,280 bits, ~4,300 digits: no CAIE answer is near it).
_MAX_POW_RESULT_BITS = _MAX_RESULT_INT_BITS

#: Address-space limit for the parse worker (see `_ParseWorker`). Measured:
#: the child's VmSize after importing SymPy is ~75 MB; under this limit
#: `2**999999999` (a 125 MB integer) raises MemoryError in 1.8 s and the
#: child survives. Small enough that the worst case fits a 1 GiB worker.
_PARSE_WORKER_MEMORY_BYTES = 512 * 1024 * 1024

#: How long a (re)started parse worker may take to report ready -- interpreter
#: start, SymPy import and one warm-up parse; measured 0.17-0.23 s plus up to
#: ~0.19 s for the first parse. Kept SEPARATE from the caller's parse
#: `timeout` so a cold start on a slow or CPU-throttled host (a fresh Cloud
#: Run instance, a coverage-instrumented CI run) is never mistaken for a
#: runaway parse: without it, the first answer after every (re)start could
#: come back unparseable. Generous because it is paid at most once per start.
_PARSE_WORKER_START_TIMEOUT = 30.0

#: After a failed start, no new start is attempted for this long (review
#: round 1): where a child can never start -- from a daemonic process, say --
#: each call would otherwise pay a spawn attempt and log a warning. Calls in
#: the cool-down return None at once; one warning per failed start.
_PARSE_WORKER_START_COOLDOWN = 30.0

#: The least budget a caller must still have, once it holds the worker's lock,
#: for a parse to be attempted (#271). Below it the caller gets ``"busy"``
#: without touching the child: a reply wait this short would end in
#: ``poll(~0)`` and, unless the reply were already there, a ``"timeout"`` that
#: kills a healthy worker and charges the next caller a respawn.
_PARSE_WORKER_MIN_REPLY_WAIT = 0.05

#: The worker's pipe protocol: ``(normalised text, vet)`` or ``None`` to stop;
#: ``(kind, payload)`` back -- see `_parse_worker_main`.
type _ParseRequest = tuple[str, bool] | None
type _ParseReply = tuple[str, object]


def _magnitude_bits(value: sympy.Expr) -> int | None:
    """Bit length of a finite number's magnitude, or ``None`` when it has none."""
    if not value.is_number or not value.is_finite:
        return None
    if value.is_Integer:
        return int(abs(value)).bit_length()
    if value.is_Rational:
        return max(int(abs(value.p)).bit_length(), int(value.q).bit_length())
    try:
        magnitude = abs(float(value))
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(magnitude):  # `float(exp(exp(exp(10))))` is inf, not an OverflowError
        return None
    return int(math.log2(magnitude)) + 1 if magnitude >= 1 else 1


def _pow_would_explode(node: sympy.Pow) -> bool:
    """Would evaluating this (still unevaluated) power build an oversized integer?

    Called by :func:`_vetted_parse` -- IN THE PARSE WORKER, never in the
    caller's process -- on every ``Pow`` of an ``evaluate=False`` parse in
    POST-order, so the node's own children have already passed this check
    and evaluating them here (``subs`` rebuilds and evaluates) costs at most
    what they were bounded to per power. Their PRODUCT is not bounded: the
    base ``((10^300+1)^1000*...*1)`` of a 405-character input evaluates to a
    25-million-bit integer, measured at 33.5 s with a 2.5 s GIL stall when
    this walk ran in the caller's process. That, and ``float()`` of a nested
    ``exp`` coming back ``inf``, is why the walk runs where the timeout and
    the memory cap apply. Free symbols are substituted with 1: ``x^(n+1)`` bounds as
    ``x^2`` and stays parseable, while ``(2+x-x)^(999*999*999)`` -- which SymPy
    would collapse to ``2**997002999`` -- bounds as the number it is. Refused
    when the exponent's magnitude exceeds :data:`_MAX_EXPONENT_VALUE`, when
    ``bits(base) * exponent`` exceeds :data:`_MAX_POW_RESULT_BITS`, or when
    either side does not bound to a finite number (fail closed) -- with one
    exception. A side that is SINGULAR at the all-ones point (``zoo``,
    ``oo``, ``nan``) is not refused on that basis: every symbol gets the
    same value, so any difference of symbols (``M - m``, ``1 - v²/c²``) is 0
    there, and refusing turned the Lorentz factor ``(1/(1-v²/c²))^(1/2)`` and
    every ``(x/(x-1))^2`` into UNPARSEABLE -- a property of the substitution
    point, not of the answer. Such a power is left to the evaluated parse,
    which runs in the killable, memory-capped :class:`_ParseWorker`
    (``2^(999*999*999 + 0/(n-1))`` is killed there at the timeout). A
    second substitution point was rejected: it would re-evaluate inner
    powers that were bounded only at 1 (``((x^999)^999)^999`` is 1 there,
    but ``3**(999**3)`` at ``x = 3``), so a legitimate answer could time out
    in its own vetting.
    """
    ones: dict[sympy.Basic | complex, sympy.Basic | complex] = {
        symbol: sympy.Integer(1) for symbol in node.free_symbols
    }
    try:
        exponent = sympy.sympify(node.exp).subs(ones).doit()
        base = sympy.sympify(node.base).subs(ones).doit()
    except Exception:
        return True
    exponent_bits = _magnitude_bits(exponent)
    if exponent_bits is None:
        return not _is_singular(exponent)
    if abs(exponent) > _MAX_EXPONENT_VALUE:
        return True
    base_bits = _magnitude_bits(base)
    if base_bits is None:
        return not _is_singular(base)
    return base_bits * math.ceil(float(abs(exponent))) > _MAX_POW_RESULT_BITS


def _is_singular(value: sympy.Expr) -> bool:
    """``zoo``/``oo``/``-oo``/``nan`` anywhere in ``value``: see :func:`_pow_would_explode`."""
    return bool(value.has(sympy.zoo, sympy.oo, sympy.S.NegativeInfinity, sympy.nan))


def _parse_normalized(normalized: str, *, evaluate: bool) -> sympy.Expr:
    """The one ``parse_expr`` call, for both the vetting parse and the evaluated one."""
    return parse_expr(
        normalized,
        transformations=_TRANSFORMATIONS,
        local_dict=dict(_UNIT_LOCAL_DICT),
        evaluate=evaluate,
    )


def _coefficient_height(expr: sympy.Basic) -> float:
    """An upper bound on every EXACT coefficient any rewriting of ``expr`` can produce.

    The L1 norm of ``expr`` read as a polynomial: ``|r|`` for a Rational;
    the sum over an ``Add``; the product over a ``Mul``; ``height(base)**k``
    for a power with a positive numeric exponent ``k``. Because
    ``|p + q| <= |p| + |q|``, ``|p * q| <= |p| * |q|`` and ``|p**k| <= |p|**k``
    hold for these norms, no ``expand``, split, ``powsimp`` or ``simplify`` of
    ``expr`` can produce an exact number larger than this -- including the
    constant term of ``(999x-999)(999y-999)(999z-999)``, whose atoms are all
    999 but whose expansion holds ``-997002999``. Everything else counts as
    1: a symbol, a Float (inexact, so SymPy never builds an exact integer
    from it), a power with a negative or symbolic exponent (an atom here;
    every power is bounded where it stands, see :func:`_evaluated_would_explode`).
    A function application counts as the largest of 1 and its arguments'
    heights, so ``log(10^300)`` -- which ``exp(k*log(n)) -> n**k`` can turn
    back into an integer -- is not a height of 1. ``inf`` on float overflow.
    """
    try:
        if expr.is_Rational:
            return float(abs(expr))
        if expr.is_Add:
            return math.fsum(_coefficient_height(arg) for arg in expr.args)
        if expr.is_Mul:
            return math.prod(_coefficient_height(arg) for arg in expr.args)
        if isinstance(expr, sympy.Pow):
            if expr.exp.is_Rational and expr.exp > 0:
                height: float = _coefficient_height(expr.base) ** float(expr.exp)
                return height
            return 1.0
        if isinstance(expr, sympy.Function):
            return max([1.0, *(_coefficient_height(arg) for arg in expr.args)])
    except OverflowError:
        return math.inf
    return 1.0


def _evaluated_would_explode(expr: sympy.Basic) -> bool:
    """Would ``expr`` -- the EVALUATED parse -- hurt the caller that receives it?

    Review round 1 of triage F2. The unevaluated walk bounds each power at
    the all-ones point, where ``999*999*999*(x-1)`` is 0; the worker then
    returned ``2**(997002999*x - 997002999)`` in 0.02 s, and the CALLER froze
    for 3.7-3.9 s in ``equivalent`` (``simplify`` splitting off
    ``2**-997002999`` with the GIL held) or never returned from
    ``sympy.expand``. Those run on the caller's side of the pipe, on exactly
    this tree, so this tree is what is bounded:

    - every exact number must print (:data:`_MAX_RESULT_INT_BITS`), which
      also bounds the reply's pickle;
    - every power and every ``exp`` must have an exponent of coefficient
      height (:func:`_coefficient_height`) at most :data:`_MAX_EXPONENT_VALUE`
      -- for ANY base: ``expand`` turns ``(x+1)**(N*y - N)`` into a
      multinomial of degree N without a number in sight, and ``simplify``
      turns ``exp(N*log(2)*(x-1))`` into ``2**-N``;
    - and a power's result must fit: ``bits(height(base)) * height(exponent)``
      at most :data:`_MAX_RESULT_INT_BITS` (``(10^300+1)**(1000*(x-1))``
      splits off a 997,000-bit integer).
    """
    for atom in expr.atoms(sympy.Rational):
        if max(abs(atom.p).bit_length(), atom.q.bit_length()) > _MAX_RESULT_INT_BITS:
            return True
    for node in sympy.preorder_traversal(expr):
        if isinstance(node, sympy.Pow):
            base_height = _coefficient_height(node.base)
            exponent_height = _coefficient_height(node.exp)
        elif isinstance(node, sympy.exp) and node.args[0].has(sympy.log):
            # Only `exp(k*log(n))` is `n**k` in disguise (review round 2):
            # without a log, `exp(-5000/T)`, `A*exp(-2000*t)` are ordinary
            # answers that no rewrite turns into an exact power.
            base_height, exponent_height = 1.0, _coefficient_height(node.args[0])
        else:
            continue
        # `not (x <= limit)`, not `x > limit`: a height that overflowed to
        # inf and met a 0 is nan, and nan must fail closed.
        if not exponent_height <= _MAX_EXPONENT_VALUE:
            return True
        base_bits = math.log2(base_height) + 1 if base_height >= 1 else 1.0
        if not base_bits * exponent_height <= _MAX_RESULT_INT_BITS:
            return True
    return False


def _vetted_parse(normalized: str, *, vet: bool = True) -> sympy.Expr | None:
    """:func:`_vet_and_parse`'s expression: ``None`` if refused at either stage."""
    return _vet_and_parse(normalized, vet=vet)[1]


def _vet_and_parse(normalized: str, *, vet: bool = True) -> tuple[str, sympy.Expr | None]:
    """Bound every power of an UNEVALUATED parse, parse for real, bound the result.

    Returns ``("ok", expr)``, or ``("refused-unevaluated", None)`` when the
    walk refused it BEFORE the evaluated parse ran (so no big-int work was
    ever done), or ``("refused-evaluated", None)`` when the result bound
    refused it after. The stage is reported to the parent
    (:attr:`_ParseWorker.last_outcome`) so a test can assert WHICH step
    refused an input rather than how long it took. Runs in the parse worker
    (see :class:`_ParseWorker`).
    The ``evaluate=False`` parse builds a tree and evaluates nothing but
    whitelisted function calls and textually-bounded factorials; the regexes
    in :func:`parse_expr_safe` read literals, and a computed exponent (triage
    F2: ``2^(999*999*999)``) needs the tree. The evaluated result is then
    bounded too (:func:`_evaluated_would_explode`), because that is the form
    the caller's ``simplify`` and ``expand`` operate on. ``vet=False`` skips
    both -- only for tests that must reach the evaluated parse with a
    known-dangerous text, to exercise the worker's own kill and memory
    bounds. Parse errors propagate to the worker loop, which reports them.
    """
    if vet:
        unevaluated = _parse_normalized(normalized, evaluate=False)
        for node in sympy.postorder_traversal(unevaluated):
            if isinstance(node, sympy.Pow) and _pow_would_explode(node):
                return ("refused-unevaluated", None)
    expr = _parse_normalized(normalized, evaluate=True)
    if vet and _evaluated_would_explode(expr):
        return ("refused-evaluated", None)
    return ("ok", expr)


def _parse_worker_main(  # pragma: no cover
    conn: Connection[_ParseReply, _ParseRequest], memory_limit: int
) -> None:
    """The parse worker's loop, run in the child (hence no coverage).

    ``(text, vet) -> ("ok", expr) | ("refused-unevaluated", None) |
    ("refused-evaluated", None) | ("memory", None) | ("error", repr)``;
    ``None`` ends the loop. See :func:`_vet_and_parse`.

    Runs in a ``spawn``ed child, so this module is imported afresh there.
    The address-space limit is set first; where ``resource`` is unavailable
    or refuses, the parent's timeout is the only bound (documented on
    :class:`_ParseWorker`). One warm-up parse runs before ``("ready", None)``
    is sent, so SymPy's first-parse cost (~0.15-0.19 s) is paid inside the
    parent's start budget, not inside a caller's parse ``timeout``.

    SIGINT is ignored: a Ctrl-C in the terminal reaches the whole process
    group, and the child's lifetime belongs to the parent (``daemon=True``
    plus the parent's kill/shutdown), not to the keyboard. A closed pipe
    (the parent exited or was killed) ends the loop quietly.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        import resource

        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, hard))
    except (ImportError, ValueError, OSError):
        pass
    _vetted_parse("2*x**2 + 1")
    try:
        conn.send(("ready", None))
        while True:
            message = conn.recv()
            if message is None:
                return
            text, vet = message
            try:
                conn.send(_vet_and_parse(text, vet=vet))
            except MemoryError:
                conn.send(("memory", None))
            except Exception as exc:
                conn.send(("error", repr(exc)))
    except (EOFError, OSError):
        return


class _ParseWorker:
    """One reusable, killable child process for ALL of the parse's SymPy work.

    Triage F2 (user decision 3, 2026-09-29). The parse is the one step of
    this module where SymPy can do C-level big-integer work that holds the
    GIL -- a thread timeout cannot interrupt it (see :func:`_run_bounded`),
    but a process can be killed. That covers the vetting walk too
    (:func:`_vetted_parse`): it evaluates bases and exponents, and a
    product of individually-bounded powers froze the caller's process for
    2.5 s at a time when the walk ran there. So the caller's process does
    only the regex guards and the pipe round-trip; the unevaluated parse,
    the walk and the evaluated parse all run here, under the timeout and
    the memory cap. Measured in this venv: a spawn start costs
    0.17-0.23 s, a warm call 0.3-0.6 ms, so ONE lazily-started worker is
    kept and reused rather than one process per call (300-700x the parse).

    Guarantees, in every failure mode, that :meth:`parse` returns ``None``
    and never raises: a timeout kills and joins the child; a MemoryError in
    the child (address space capped at :data:`_PARSE_WORKER_MEMORY_BYTES`)
    is reported and the child lives on; a crash or broken pipe is joined and
    the next call respawns; a child that cannot be started, or does not
    report ready within :data:`_PARSE_WORKER_START_TIMEOUT`, is killed and
    the call returns ``None``. The caller's ``timeout`` covers the wait for
    the lock and the parse; a start the caller performs itself is not
    charged to it, but a start performed by ANOTHER caller holding the lock
    is, because it is part of this caller's wait for the lock. ``spawn``,
    never ``fork``: the web server runs sync routes on threads. Calls are
    serialised by a lock (one worker per parent), and the wait for it counts
    against the caller's own ``timeout``: a caller that cannot take the
    worker in time returns ``None`` with the outcome ``"busy"`` without
    touching the child, so no caller waits past its own deadline behind a
    runaway sibling (#271). The owner pid is
    recorded, and an ``os.register_at_fork`` hook resets the lock and
    forgets the child in a forked process, so a pre-forked server worker or
    a forking test harness starts its own child instead of sharing a pipe or
    inheriting a held lock. The child is a
    daemon, so ``multiprocessing``'s atexit hook terminates it with the
    parent; :meth:`shutdown` does so explicitly.

    The child never runs the parent's ``__main__``: ``spawn`` would re-run a
    path-run script (or a ``-m`` module not named ``__main__``) in the child,
    before its memory cap is set, and a script that called
    :func:`parse_expr_safe` at import time without an
    ``if __name__ == "__main__":`` guard then had the child start a nested
    worker of its own. :func:`~lemely.runtime.process_start.start_without_parent_main`
    starts it, as it starts the scan workers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: BaseProcess | None = None
        self._conn: Connection[_ParseRequest, _ParseReply] | None = None
        self._owner_pid: int | None = None
        #: `time.monotonic()` of the last failed start, for the cool-down.
        self._start_failed_at: float | None = None
        #: How the most recent :meth:`parse` ended, on any thread -- a
        #: diagnostic for tests, which assert on the STEP that refused an
        #: input instead of on elapsed time. Written without the lock (the
        #: busy outcome never holds it), so it is unsynchronised and only
        #: tests may read it; a caller that needs its own outcome uses
        #: :meth:`parse_with_outcome` (:func:`parse_expr_outcome`). Values:
        #: "ok", "refused-unevaluated", "refused-evaluated", "memory", "error", "timeout", "crash",
        #: "interrupted", "unavailable" (no worker could be started) or
        #: "busy" (the lock was not free within the caller's timeout, or left
        #: less than :data:`_PARSE_WORKER_MIN_REPLY_WAIT` of it).
        self.last_outcome: str | None = None

    def _forget_after_fork(self) -> None:
        """In a forked child: the parent's worker, pipe and lock are not ours."""
        self._lock = threading.Lock()
        self._process = self._conn = self._owner_pid = None
        self._start_failed_at = None

    def _start(self) -> bool:
        """Start a child, or ``False`` after ONE warning if it cannot.

        After a failure, ``False`` without trying for
        :data:`_PARSE_WORKER_START_COOLDOWN` seconds.
        """
        failed_at = self._start_failed_at
        if failed_at is not None and time.monotonic() - failed_at < _PARSE_WORKER_START_COOLDOWN:
            return False
        started = self._spawn()
        self._start_failed_at = None if started else time.monotonic()
        return started

    def _spawn(self) -> bool:
        context = multiprocessing.get_context("spawn")
        try:
            parent_conn, child_conn = context.Pipe()
        except OSError:  # out of file descriptors
            _logger.warning("parse worker not started: no pipe", exc_info=True)
            return False
        process = context.Process(
            target=_parse_worker_main,
            args=(child_conn, _PARSE_WORKER_MEMORY_BYTES),
            name="lemely-parse-worker",
            daemon=True,
        )
        try:
            start_without_parent_main(process)
        except BaseException as exc:  # e.g. a daemonic parent, out of fds -- or an interrupt
            parent_conn.close()
            child_conn.close()
            if process.pid is not None:  # spawned before the failure: never leave it running
                process.kill()
                process.join()
            if not isinstance(exc, Exception):
                raise
            _logger.warning("parse worker not started; parse_expr_safe returns None", exc_info=True)
            return False
        child_conn.close()
        self._process, self._conn, self._owner_pid = process, parent_conn, os.getpid()
        try:
            ready = parent_conn.poll(_PARSE_WORKER_START_TIMEOUT)
            ready = ready and parent_conn.recv() == ("ready", None)
        except (EOFError, OSError):
            ready = False
        except BaseException:  # interrupted mid-handshake: an unread "ready" would desync
            self._discard(kill=True)
            raise
        if not ready:
            _logger.warning("parse worker did not report ready; parse_expr_safe returns None")
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

    def _ready(self) -> bool:
        if self._process is None or self._owner_pid != os.getpid():
            # A foreign or never-started worker: never joined here.
            self._process = self._conn = None
            return self._start()
        if not self._process.is_alive():
            self._discard(kill=False)
            return self._start()
        return True

    def parse(self, text: str, timeout: float, *, vet: bool = True) -> sympy.Expr | None:
        """:meth:`parse_with_outcome`'s expression, without the outcome."""
        return self.parse_with_outcome(text, timeout, vet=vet)[0]

    def _finish(self, expr: sympy.Expr | None, outcome: str) -> tuple[sympy.Expr | None, str]:
        # Unsynchronised: the busy outcome is written without the lock, and
        # any thread may overwrite it. Only tests read `last_outcome`.
        self.last_outcome = outcome
        return expr, outcome

    def parse_with_outcome(
        self, text: str, timeout: float, *, vet: bool = True
    ) -> tuple[sympy.Expr | None, str]:
        """``text`` vetted and parsed in the child (:func:`_vetted_parse`), with how it ended.

        The expression is ``None`` when the vetting walk refuses it, and on
        timeout, memory, crash or parse error; the outcome says which (see
        :attr:`last_outcome` for the values). When the lock is not free
        within ``timeout``, or frees up with under
        :data:`_PARSE_WORKER_MIN_REPLY_WAIT` of it left, the expression is
        ``None`` and the outcome ``"busy"``; the child is then left
        untouched. The wait for the lock and the parse share one deadline. A
        child start inside :meth:`_ready` extends it by the time the start
        took, so a start THIS caller performs does not eat its budget; a
        start another caller performs while holding the lock does, as part
        of the wait for the lock. ``vet=False`` is for tests only (see
        there).
        """
        deadline = time.monotonic() + timeout
        # Bound once: `_forget_after_fork` replaces `self._lock`, and the
        # release must be of the object this call acquired.
        lock = self._lock
        if not lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return self._finish(None, "busy")
        try:
            if deadline - time.monotonic() < _PARSE_WORKER_MIN_REPLY_WAIT:
                # The lock wait left no budget worth a parse: do not poll ~0 and
                # then kill a healthy child for it.
                return self._finish(None, "busy")
            started = time.monotonic()
            ready = self._ready()
            deadline += time.monotonic() - started
            if not ready or self._conn is None:
                return self._finish(None, "unavailable")
            conn = self._conn
            try:
                conn.send((text, vet))
                if not conn.poll(max(0.0, deadline - time.monotonic())):
                    self._discard(kill=True)
                    return self._finish(None, "timeout")
                kind, value = conn.recv()
            except Exception:  # EOFError/OSError on a crash, or an unpicklable reply
                self._discard(kill=True)
                return self._finish(None, "crash")
            except BaseException:
                # KeyboardInterrupt/SystemExit while the reply is outstanding:
                # a live worker would hand THIS text's reply to the next
                # caller (review round 1), so it is killed before propagating.
                self._discard(kill=True)
                self._finish(None, "interrupted")
                raise
            if kind != "ok" or not isinstance(value, sympy.Basic):
                return self._finish(None, kind)
            # Any Basic, exactly as the in-process parse returned before (a
            # relational is not an Expr); parse_expr_safe applies the same test.
            return self._finish(cast("sympy.Expr", value), kind)
        finally:
            lock.release()

    def pid(self) -> int | None:
        process = self._process
        return None if process is None else process.pid

    def shutdown(self) -> None:
        with self._lock:
            if self._owner_pid is not None and self._owner_pid != os.getpid():
                # Another process's child (no fork hook on this platform):
                # not ours to signal or join. The lock is NOT replaced here --
                # a thread may be waiting on it.
                self._process = self._conn = self._owner_pid = None
                return
            if self._conn is not None:
                with contextlib.suppress(OSError):
                    self._conn.send(None)
            self._discard(kill=True)


_PARSE_WORKER = _ParseWorker()
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_PARSE_WORKER._forget_after_fork)
