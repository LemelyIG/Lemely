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
        self.assertEqual(
            result.returncode,
            0,
            msg=f"import-linter reported violations:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
