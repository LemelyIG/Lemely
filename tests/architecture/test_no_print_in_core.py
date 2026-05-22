"""Walks lemely/core/ AST and asserts zero print() calls outside docstrings."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "lemely" / "core"


class NoPrintInCoreTests(unittest.TestCase):
    def test_no_print_calls(self) -> None:
        offenders: list[str] = []
        for path in _CORE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    offenders.append(f"{path.relative_to(_CORE.parent.parent)}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            msg=f"print() calls in lemely.core (must be stderr-only via structlog): {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
