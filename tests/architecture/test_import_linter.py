"""Runs import-linter contracts as a pytest test; fails on any violation."""

from __future__ import annotations

import subprocess
import unittest


class ImportLinterTests(unittest.TestCase):
    def test_all_contracts_pass(self) -> None:
        result = subprocess.run(
            ["lint-imports"],
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
