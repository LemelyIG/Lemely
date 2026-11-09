"""Every worker thread under lemely/io runs in a copied context (billing spec §5.7).

The usage meter's cost accumulator is a contextvar. A pool task submitted without
``contextvars.copy_context().run`` would make its model calls outside the job's scope, and
that cost would never be charged. This scans the source, so a new pool fails here first.

The scan is deliberately wider than "``pool.submit`` is wrapped":

- every ``.submit`` / ``.apply_async`` / ``.map`` style dispatch is checked on any receiver,
  and an alias (``submit = pool.submit``) or ``getattr(pool, "submit")`` is refused outright;
- every way of starting a worker (``ThreadPoolExecutor``, ``ProcessPoolExecutor``,
  ``ThreadPool``, ``Pool``, ``Thread``, a ``Thread`` subclass, ``Timer``, ``Process``,
  ``_thread.start_new_thread``, ``run_in_executor``), also when imported under another name or
  fetched with ``getattr``
  is refused unless the file is on a per-file allowlist with a reason.

The accepted way to submit is ``pool.submit(contextvars.copy_context().run, fn, *args)``
(``copy_context().run`` imported by name is accepted too).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_IO = Path(__file__).resolve().parents[2] / "lemely" / "io"

#: Dispatch methods that run a callable on a worker.
_SUBMIT_METHODS = frozenset({"submit", "apply_async", "map_async"})
#: Dispatch methods that cannot carry ``copy_context().run`` for a single task, so each
#: allowed call site is a ``(file, enclosing function)`` pair with the reason it is unpriced.
_MAP_METHODS = frozenset({"map", "imap", "imap_unordered", "starmap", "starmap_async"})
#: Constructors that start a worker, whatever the receiver.
_WORKER_STARTERS = frozenset(
    {
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
        "ThreadPool",
        "Pool",
        "Thread",
        "Timer",
        "Process",
        "start_new_thread",
        "start_joinable_thread",
        "run_in_executor",
    }
)

#: ``.map``-style call sites whose workers make no priced model call.
_MAP_ALLOWED: dict[tuple[str, str], str] = {
    ("llm/image_fit.py", "_fit_steps"): "CPU-only image fitting",
    ("llm/claude_uploads.py", "_upload_all"): "Files API uploads are not billed per token",
}

#: Files that may construct a pool, and the starter they use. Each ``submit`` in them is
#: still checked above, so this only records that the file has been reviewed.
_STARTERS_ALLOWED: dict[tuple[str, str], str] = {
    ("answer_extraction.py", "ThreadPoolExecutor"): "re-read pool; submits copy the context",
    ("binding/chunked_read.py", "ThreadPoolExecutor"): "chunk reads; submits copy the context",
    ("binding/orchestrate.py", "ThreadPoolExecutor"): "binding legs; submits copy the context",
    ("gemini.py", "ThreadPoolExecutor"): "uploads and deletes; submits copy the context",
    ("llm/claude_uploads.py", "ThreadPoolExecutor"): "unpriced Files API uploads (map)",
    ("llm/image_fit.py", "ThreadPoolExecutor"): "CPU-only image fitting (map)",
}


def _is_copied_run(node: ast.expr) -> bool:
    """``contextvars.copy_context().run`` or ``copy_context().run``."""
    if not (isinstance(node, ast.Attribute) and node.attr == "run"):
        return False
    inner = node.value
    if not isinstance(inner, ast.Call):
        return False
    func = inner.func
    return (isinstance(func, ast.Attribute) and func.attr == "copy_context") or (
        isinstance(func, ast.Name) and func.id == "copy_context"
    )


def _name_of(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.scope: list[str] = []
        self.found: list[str] = []
        self._dispatch_funcs: set[int] = set()

    def _flag(self, node: ast.AST, why: str) -> None:
        self.found.append(f"{self.rel}:{getattr(node, 'lineno', 0)}: {why}")

    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(_name_of(base) == "Thread" for base in node.bases):
            self._flag(node, f"class {node.name} subclasses Thread")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # ``from threading import Thread as T`` would hide the constructor from the name check.
        for alias in node.names:
            if alias.asname and alias.name in _WORKER_STARTERS | _SUBMIT_METHODS | _MAP_METHODS:
                self._flag(node, f"{alias.name} imported as {alias.asname} hides a worker")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = _name_of(func)
        if isinstance(func, ast.Attribute):
            self._dispatch_funcs.add(id(func))
        if name in _WORKER_STARTERS and (self.rel, name) not in _STARTERS_ALLOWED:
            self._flag(node, f"{name} starts a worker outside a copied context")
        if (
            isinstance(func, ast.Attribute)
            and name in _SUBMIT_METHODS
            and (not node.args or not _is_copied_run(node.args[0]))
        ):
            self._flag(node, f".{name} without contextvars.copy_context().run")
        if isinstance(func, ast.Attribute) and name in _MAP_METHODS:
            enclosing = self.scope[-1] if self.scope else "<module>"
            if (self.rel, enclosing) not in _MAP_ALLOWED:
                self._flag(node, f".{name} in {enclosing} runs tasks in the caller's context")
        if (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _SUBMIT_METHODS | _MAP_METHODS | _WORKER_STARTERS
        ):
            self._flag(node, f"getattr(..., {node.args[1].value!r}) hides a dispatch")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # A dispatch method used as a value (``submit = pool.submit``) escapes the call checks.
        if node.attr in _SUBMIT_METHODS | _MAP_METHODS and id(node) not in self._dispatch_funcs:
            self._flag(node, f"alias of .{node.attr} hides a dispatch")
        self.generic_visit(node)


def violations(source: str, rel: str) -> list[str]:
    """Every way ``source`` (the file ``rel`` under ``lemely/io``) could escape the scope."""
    scan = _Scan(rel)
    scan.visit(ast.parse(source))
    return scan.found


def test_lemely_io_runs_every_worker_in_a_copied_context() -> None:
    offenders = []
    for path in sorted(_IO.rglob("*.py")):
        rel = path.relative_to(_IO).as_posix()
        offenders += violations(path.read_text(encoding="utf-8"), rel)
    assert offenders == [], (
        "submit as pool.submit(contextvars.copy_context().run, fn, ...), or allowlist the "
        "site with a reason if it makes no priced call"
    )


def test_allowlists_name_real_sites() -> None:
    """A stale allowlist entry would silently permit a future, unrelated site."""
    starters: set[tuple[str, str]] = set()
    maps: set[tuple[str, str]] = set()
    for path in sorted(_IO.rglob("*.py")):
        rel = path.relative_to(_IO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _name_of(node.func) in _WORKER_STARTERS:
                starters.add((rel, str(_name_of(node.func))))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in _MAP_METHODS
                    ):
                        maps.add((rel, node.name))
    assert starters == set(_STARTERS_ALLOWED)
    assert set(_MAP_ALLOWED) <= maps


_RED = {
    "unwrapped submit": ("with TPE() as pool:\n    pool.submit(f, 1)\n", "without"),
    "submit on another receiver": ("self._ex.submit(f)\n", "without"),
    "apply_async": ("p.apply_async(f)\n", "without"),
    "executor.map": (
        "def work(xs):\n    with TPE() as executor:\n        executor.map(f, xs)\n",
        ".map in work",
    ),
    "attribute-receiver map": ("def work(self, xs):\n    self._pool.map(f, xs)\n", ".map in work"),
    "module-level map": ("pool.map(f, xs)\n", "<module>"),
    "submit alias": ("submit = pool.submit\nsubmit(f)\n", "alias of .submit"),
    "getattr submit": ("getattr(pool, 'submit')(f)\n", "hides a dispatch"),
    "ThreadPoolExecutor": ("ex = ThreadPoolExecutor(2)\n", "ThreadPoolExecutor starts"),
    "concurrent.futures.ThreadPoolExecutor": (
        "ex = futures.ThreadPoolExecutor(2)\n",
        "ThreadPoolExecutor starts",
    ),
    "ProcessPoolExecutor": ("ex = ProcessPoolExecutor(2)\n", "ProcessPoolExecutor starts"),
    "ThreadPool": ("p = multiprocessing.pool.ThreadPool(2)\n", "ThreadPool starts"),
    "Thread": ("threading.Thread(target=f).start()\n", "Thread starts"),
    "bare Thread name": ("Thread(target=f).start()\n", "Thread starts"),
    "Thread subclass": ("class W(threading.Thread):\n    pass\n", "subclasses Thread"),
    "Timer": ("threading.Timer(0, f).start()\n", "Timer starts"),
    "run_in_executor": ("loop.run_in_executor(None, f)\n", "run_in_executor starts"),
    "multiprocessing.Process": ("multiprocessing.Process(target=f).start()\n", "Process starts"),
    "_thread.start_new_thread": ("_thread.start_new_thread(f, ())\n", "start_new_thread starts"),
    "aliased Thread import": (
        "from threading import Thread as T\nT(target=f).start()\n",
        "imported as T",
    ),
    "aliased Timer import": (
        "from threading import Timer as Tm\nTm(0, f).start()\n",
        "imported as Tm",
    ),
    "aliased start_new_thread import": (
        "from _thread import start_new_thread as go\ngo(f, ())\n",
        "imported as go",
    ),
    "aliased executor import": (
        "from concurrent.futures import ThreadPoolExecutor as TPE\nTPE(2)\n",
        "imported as TPE",
    ),
    "getattr Thread": ("getattr(threading, 'Thread')(target=f).start()\n", "hides a dispatch"),
    "getattr Timer": ("getattr(threading, 'Timer')(0, f).start()\n", "hides a dispatch"),
}


@pytest.mark.parametrize(("source", "expected"), list(_RED.values()), ids=list(_RED))
def test_scan_flags_every_bypass_form(source: str, expected: str) -> None:
    found = violations(source, "synthetic.py")
    assert found, f"not flagged: {source!r}"
    assert any(expected in line for line in found), found


@pytest.mark.parametrize(
    "source",
    [
        "pool.submit(contextvars.copy_context().run, f, 1)\n",
        "from contextvars import copy_context\npool.submit(copy_context().run, f)\n",
    ],
)
def test_scan_accepts_the_copied_run_form(source: str) -> None:
    assert violations(source, "synthetic.py") == []


def test_unwrapped_map_in_an_allowlisted_file_is_still_flagged() -> None:
    """The map allowlist is per function, so a new site in the same file is caught."""
    source = "def _other(pool, xs):\n    pool.map(f, xs)\n"
    assert violations(source, "llm/image_fit.py")
    assert not violations(source.replace("_other", "_fit_steps"), "llm/image_fit.py")
