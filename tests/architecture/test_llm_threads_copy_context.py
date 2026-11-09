"""Every worker thread under lemely/io runs in a copied context (billing spec §5.7).

The usage meter's cost accumulator is a contextvar. A pool task submitted without
``contextvars.copy_context().run`` would make its model calls outside the job's scope, and
that cost would never be charged. This scans the source, so a new pool fails here first.
"""

from __future__ import annotations

import ast
from pathlib import Path

_IO = Path(__file__).resolve().parents[2] / "lemely" / "io"

#: ``pool.map`` call sites whose workers make no priced model call, with the reason.
_MAP_ALLOWED = {
    "llm/image_fit.py": "CPU-only image fitting",
    "llm/claude_uploads.py": "Files API uploads are not billed per token",
}


def _calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_copied_run(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "run"
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "attr", None) == "copy_context"
    )


def test_every_pool_submit_copies_the_context() -> None:
    offenders = []
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "submit":
                if not call.args or not _is_copied_run(call.args[0]):
                    offenders.append(f"{path.relative_to(_IO)}:{call.lineno}")
    assert offenders == []


def test_pool_map_only_where_no_model_call_runs() -> None:
    found = set()
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "map"
                and getattr(func.value, "id", None) == "pool"
            ):
                found.add(path.relative_to(_IO).as_posix())
    assert found <= set(_MAP_ALLOWED), found - set(_MAP_ALLOWED)


def test_no_bare_threads_under_io() -> None:
    offenders = []
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "Thread":
                offenders.append(f"{path.relative_to(_IO)}:{call.lineno}")
    assert offenders == []
