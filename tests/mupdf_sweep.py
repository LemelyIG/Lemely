"""Source sweeps over ``lemely/``: who may open a PDF with MuPDF, and who may
make a :class:`~lemely.io.pdf_prescan.PrescannedPdf`.

"Pre-scan before any MuPDF open" is enforced by code, not by each caller
remembering: user PDF bytes reach MuPDF only through the sanctioned openers
(:data:`ALLOWED_OPENS`), and only ``prescan_pdf`` vouches for a pre-scan
(:data:`ALLOWED_PRESCANNED`). The repo-level assertions live in
``SanctionedOpenerSweepTests`` (``tests/test_scan_limits.py``); the evasion
self-tests, which prove each form below goes red, live in
``tests/test_mupdf_sweep.py``.

What :func:`find_mupdf_opens` sees (a finding is ``(filename, enclosing
function or "<module>")``):

* a call with arguments through a binding of ``pymupdf`` or ``fitz``:
  ``import pymupdf [as x]`` / ``import fitz [as x]`` then ``x.open(...)`` or
  ``x.Document(...)``; ``from pymupdf import open|Document [as y]`` (or
  ``from fitz``, or ``import *``) then ``y(...)``; and one level of aliasing by
  assignment, ``z = pymupdf``, ``z = pymupdf.open``, ``z = pymupdf.Document``
  (plain or annotated, chained targets allowed), then ``z.open(...)`` or
  ``z(...)``. Bindings are resolved per scope (module, function, class; a
  class body is not visible to its methods), and the function name reported is
  the innermost enclosing ``def``;
* every ``.insert_pdf`` and ``.insert_file`` attribute, called or not, because
  grafting a document into another is an open of its bytes;
* not a bare ``pymupdf.open()``: with no arguments it makes a new, empty
  document and opens nothing.

What it cannot see. Each is reviewer territory, and
``MupdfOpenKnownBlindSpotTests`` pins them so this list cannot drift:

* ``getattr(pymupdf, "open")`` and ``importlib.import_module("pymupdf")`` (the
  module is never bound to a name the sweep reads);
* aliasing deeper than one assignment (``a = pymupdf; b = a; b.open(x)``), and
  an alias made by tuple unpacking, in a container, or by a parameter default;
* the opener used as a value rather than called (``map(pymupdf.open, xs)``,
  ``functools.partial(pymupdf.open, ...)``, returning ``pymupdf.open``): a type
  use such as ``pymupdf.Document`` in an annotation or ``isinstance`` is common,
  so a bare reference is not flagged;
* calls built from strings or other data (``eval``, ``exec``, ``__import__``);
* the low-level ``pymupdf.mupdf`` bindings (``fz_open_document_with_buffer``
  and kin), which ``pdf_canonical`` imports for its own graft work;
* a name shadowed in an inner scope (``def f(pymupdf): pymupdf.open(x)`` is
  reported, which is the safe direction), and rebinding after the fact
  (``o = pymupdf.open; o = something_else; o(x)`` is reported too);
* any other library that opens a PDF (pypdfium2 has its own gate, in
  ``pdf_canonical``'s renderers).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ALLOWED_OPENS",
    "ALLOWED_PRESCANNED",
    "find_mupdf_opens",
    "find_prescanned_constructions",
    "sweep",
]

#: Every place in ``lemely/`` allowed to open (or graft) MuPDF bytes. The
#: ``_copy_pages`` entry is its ``insert_pdf``; the other two are ``pymupdf.open``.
ALLOWED_OPENS: set[tuple[str, str]] = {
    ("lemely/io/pdf_canonical.py", "open_checked_pdf"),
    ("lemely/io/pdf_canonical.py", "open_scan_image_document"),
    ("lemely/io/pdf_canonical.py", "_copy_pages"),
}
#: The one place in ``lemely/`` allowed to make a ``PrescannedPdf``.
ALLOWED_PRESCANNED: set[tuple[str, str]] = {("lemely/io/pdf_prescan.py", "prescan_pdf")}

_PACKAGES = frozenset({"pymupdf", "fitz"})
_OPENER_NAMES = frozenset({"open", "Document"})
_GRAFT_METHODS = frozenset({"insert_pdf", "insert_file"})
_MODULE = "module"
_OPENER = "opener"
_Finding = tuple[str, str]
_Scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


@dataclass
class _Scope:
    """The names one scope binds to ``pymupdf``/``fitz`` or to an opener."""

    is_class: bool = False
    #: Bound by an import: name -> ``_MODULE`` or ``_OPENER``.
    imports: dict[str, str] = field(default_factory=dict)
    #: Bound by assigning an import-bound name: one level, never an alias of an alias.
    aliases: dict[str, str] = field(default_factory=dict)


def _own_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Every node in ``body`` that belongs to this scope, nested scopes left out."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _Scopes):
            stack.extend(ast.iter_child_nodes(node))


def _classify(expr: ast.expr, lookup: Callable[[str], str | None]) -> str | None:
    """``_MODULE``, ``_OPENER`` or ``None`` for ``expr`` under ``lookup``."""
    if isinstance(expr, ast.Name):
        return lookup(expr.id)
    if (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.attr in _OPENER_NAMES
        and lookup(expr.value.id) == _MODULE
    ):
        return _OPENER
    return None


def _build_scope(body: list[ast.stmt], parents: list[_Scope], *, is_class: bool) -> _Scope:
    """``body``'s bindings; ``parents`` is the chain visible from this scope."""
    scope = _Scope(is_class=is_class)
    nodes = list(_own_nodes(body))
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _PACKAGES:
                    continue
                if alias.asname is None:
                    scope.imports[root] = _MODULE  # ``import pymupdf.mupdf`` binds ``pymupdf``
                elif "." not in alias.name:
                    scope.imports[alias.asname] = _MODULE
                # ``import pymupdf.mupdf as m`` binds the submodule, not the package.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in _PACKAGES:
            for alias in node.names:
                if alias.name == "*":
                    scope.imports.update(dict.fromkeys(_OPENER_NAMES, _OPENER))
                elif alias.name in _OPENER_NAMES:
                    scope.imports[alias.asname or alias.name] = _OPENER
    chain = [scope, *parents]

    def imported(name: str) -> str | None:
        return next((s.imports[name] for s in chain if name in s.imports), None)

    for node in nodes:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        kind = _classify(value, imported)
        if kind is not None:
            for target in targets:
                if isinstance(target, ast.Name):
                    scope.aliases[target.id] = kind
    return scope


class _Visitor(ast.NodeVisitor):
    """Walks one module tracking the scope chain and the enclosing function."""

    def __init__(self, filename: str, tree: ast.Module) -> None:
        self.filename = filename
        self.functions: list[str] = []
        self.found: set[_Finding] = set()
        self.chain: list[_Scope] = [_build_scope(tree.body, [], is_class=False)]

    def _where(self) -> str:
        return self.functions[-1] if self.functions else "<module>"

    def _lookup(self, name: str) -> str | None:
        for scope in self.chain:
            kind = scope.aliases.get(name) or scope.imports.get(name)
            if kind is not None:
                return kind
        return None

    def _record(self) -> None:
        self.found.add((self.filename, self._where()))

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Decorators and defaults run in the enclosing scope; annotations are
        # type uses and are not walked.
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        visible = [scope for scope in self.chain if not scope.is_class]
        outer = self.chain
        self.chain = [_build_scope(node.body, visible, is_class=False), *visible]
        self.functions.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.functions.pop()
        self.chain = outer

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in [*node.decorator_list, *node.bases, *(kw.value for kw in node.keywords)]:
            self.visit(expr)
        outer = self.chain
        self.chain = [_build_scope(node.body, list(outer), is_class=True), *outer]
        for statement in node.body:
            self.visit(statement)
        self.chain = outer

    def visit_Call(self, node: ast.Call) -> None:
        if (node.args or node.keywords) and _classify(node.func, self._lookup) == _OPENER:
            self._record()
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _GRAFT_METHODS:
            self._record()
        self.generic_visit(node)


def find_mupdf_opens(source: str, filename: str) -> set[tuple[str, str]]:
    """``(filename, enclosing function or "<module>")`` for each MuPDF open in ``source``.

    See the module docstring for the forms seen and the forms not.
    """
    tree = ast.parse(source)
    visitor = _Visitor(filename, tree)
    for statement in tree.body:
        visitor.visit(statement)
    return visitor.found


class _PrescannedVisitor(ast.NodeVisitor):
    def __init__(self, filename: str, tree: ast.Module) -> None:
        self.filename = filename
        self.functions: list[str] = []
        self.found: set[_Finding] = set()
        self.names = {"PrescannedPdf"}
        # Imported under another name, or assigned to one (one level).
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.names.update(
                    a.asname for a in node.names if a.name == "PrescannedPdf" and a.asname
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Name)
                and node.value.id in self.names
            ):
                self.names.update(t.id for t in node.targets if isinstance(t, ast.Name))

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in self.names or (isinstance(func, ast.Attribute) and func.attr == "PrescannedPdf"):
            self.found.add((self.filename, self.functions[-1] if self.functions else "<module>"))
        self.generic_visit(node)


def find_prescanned_constructions(source: str, filename: str) -> set[tuple[str, str]]:
    """``(filename, enclosing function or "<module>")`` for each ``PrescannedPdf(...)`` call.

    Follows ``from m import PrescannedPdf as P`` and ``z = PrescannedPdf``. It
    cannot see a ``PrescannedPdf`` made by ``dataclasses.replace``,
    ``copy.copy`` or ``object.__new__``, or one reached through ``getattr``.
    """
    tree = ast.parse(source)
    visitor = _PrescannedVisitor(filename, tree)
    visitor.visit(tree)
    return visitor.found


def sweep(root: Path, finder: Callable[[str, str], set[tuple[str, str]]]) -> set[tuple[str, str]]:
    """Union of ``finder(source, relative path)`` over every ``root/lemely/**/*.py``."""
    found: set[tuple[str, str]] = set()
    for path in sorted((root / "lemely").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        found |= finder(path.read_text(encoding="utf-8"), relative)
    return found
