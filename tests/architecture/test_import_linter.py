"""Runs import-linter contracts as a pytest test; fails on any violation."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


def _lint_imports_command() -> str:
    """Resolve `lint-imports` next to the running interpreter.

    A bare name only resolves when the venv is activated, so an unactivated
    run (`.venv/bin/python -m pytest`, as the gate sweep invokes it) failed
    with FileNotFoundError instead of checking the contracts.
    """
    script = Path(sys.executable).parent / "lint-imports"
    return str(script) if script.exists() else "lint-imports"


class ImportLinterTests(unittest.TestCase):
    def test_all_contracts_pass(self) -> None:
        result = subprocess.run(
            [_lint_imports_command()],
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_summary = result.stdout[:500] if result.stdout else ""
        stderr_summary = result.stderr[:200] if result.stderr else ""
        self.assertEqual(
            result.returncode,
            0,
            msg=f"import-linter violations:\n{stdout_summary}\n{stderr_summary}",
        )


if __name__ == "__main__":
    unittest.main()
