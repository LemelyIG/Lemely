"""Unit tests for lemely.io.cost_ledger.CostLedger."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import structlog

from lemely.io.cost_ledger import CostLedger
from tests.conftest import RepoLedgerWriteAttempted


class CostLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "sub" / "gemini_spend.json"

    def test_total_absent_file_is_zero(self) -> None:
        self.assertEqual(CostLedger(self.path).total(), 0.0)

    def test_add_accumulates(self) -> None:
        ledger = CostLedger(self.path)
        ledger.add(1.5, thresholds=[])
        ledger.add(2.25, thresholds=[])
        self.assertAlmostEqual(ledger.total(), 3.75)

    def test_persistence_across_instances(self) -> None:
        """Writing with one instance is readable by a NEW instance on the same
        file — proves the ledger survives across 'processes'."""
        writer = CostLedger(self.path)
        writer.add(5.0, thresholds=[])
        # A brand-new object (simulating a fresh process) reads the same total.
        reader = CostLedger(self.path)
        self.assertAlmostEqual(reader.total(), 5.0)
        # A further add from the reader also persists cumulatively.
        reader.add(1.0, thresholds=[])
        self.assertAlmostEqual(CostLedger(self.path).total(), 6.0)

    def test_threshold_crossed_exactly_once(self) -> None:
        ledger = CostLedger(self.path)
        # First add crosses $4 but not $6.
        total, crossed = ledger.add(4.5, thresholds=[4.0, 6.0])
        self.assertAlmostEqual(total, 4.5)
        self.assertEqual(crossed, [4.0])
        # Second add stays above $4 — $4 must NOT fire again; crosses $6 now.
        total, crossed = ledger.add(2.0, thresholds=[4.0, 6.0])
        self.assertAlmostEqual(total, 6.5)
        self.assertEqual(crossed, [6.0])
        # Third add crosses nothing new.
        total, crossed = ledger.add(1.0, thresholds=[4.0, 6.0])
        self.assertEqual(crossed, [])

    def test_multiple_thresholds_crossed_in_one_add_sorted(self) -> None:
        ledger = CostLedger(self.path)
        total, crossed = ledger.add(7.0, thresholds=[6.0, 4.0])
        self.assertAlmostEqual(total, 7.0)
        self.assertEqual(crossed, [4.0, 6.0])

    def test_threshold_persists_across_instances(self) -> None:
        """warnings_sent survives across instances — a threshold crossed in one
        'process' does not re-fire in the next."""
        CostLedger(self.path).add(4.5, thresholds=[4.0, 6.0])
        _, crossed = CostLedger(self.path).add(0.1, thresholds=[4.0, 6.0])
        self.assertEqual(crossed, [])

    def test_corrupt_file_treated_as_zero_and_logged(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ this is not valid json", encoding="utf-8")
        with structlog.testing.capture_logs() as captured:
            self.assertEqual(CostLedger(self.path).total(), 0.0)
        events = [entry.get("event") for entry in captured]
        self.assertIn(
            "cost_ledger_corrupt",
            events,
            f"expected a corrupt-ledger warning, got: {captured}",
        )

    def test_write_failure_cleans_up_tempfile(self) -> None:
        """A failure during the atomic write removes the temp file and re-raises."""
        from unittest.mock import patch

        ledger = CostLedger(self.path)
        with patch("os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            ledger.add(1.0, thresholds=[])
        # No stray temp files left behind in the ledger directory.
        leftovers = list(self.path.parent.glob(".gemini_spend_*"))
        self.assertEqual(leftovers, [])

    def test_add_after_corrupt_starts_from_zero(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("garbage", encoding="utf-8")
        ledger = CostLedger(self.path)
        total, _ = ledger.add(2.0, thresholds=[])
        self.assertAlmostEqual(total, 2.0)


class RepoLedgerWriteGuardTests(unittest.TestCase):
    """Regression tests for the session-scoped `_forbid_repo_ledger_writes`
    fixture in tests/conftest.py (issue #114). The fixture is autouse, so it
    is already active for every test in this process."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "sub" / "gemini_spend.json"

    def test_repo_internal_path_raises_and_never_writes(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        target = repo_root / "outputs" / "gemini_spend_TEST_GUARD_SHOULD_NOT_EXIST.json"
        self.assertFalse(target.exists())
        ledger = CostLedger(target)
        try:
            with self.assertRaises(RepoLedgerWriteAttempted):
                ledger.add(1.0, thresholds=[])
        finally:
            # Guard must fire before any write — assert no file was created,
            # then clean up defensively in case the guard failed to fire.
            if target.exists():
                target.unlink()
        self.assertFalse(target.exists())

    def test_guard_survives_a_broad_except_exception_handler(self) -> None:
        """The guard must not be swallowable by application error handling.

        This is the load-bearing property, not a style choice. While #114 was
        being fixed, an earlier revision raised ``RuntimeError`` and
        ``correct_paper``'s broad ``except Exception`` caught it: the real
        ledger was protected, but
        ``test_mark_submission_low_confidence_non_mcq_queues_review`` went on
        passing while silently exercising the error-fallback path instead of
        the ``confidence=0.5`` path it documents. A blocked write that nobody
        can see is a test-integrity bug wearing the fix's clothes, so the
        exception deliberately derives from ``BaseException``.
        """
        repo_root = Path(__file__).resolve().parent.parent
        target = repo_root / "outputs" / "gemini_spend_TEST_GUARD_UNMASKABLE.json"
        ledger = CostLedger(target)
        swallowed = False
        try:
            try:
                ledger.add(1.0, thresholds=[])
            except Exception:  # deliberately mimics correct_paper's broad handler
                swallowed = True
        except RepoLedgerWriteAttempted:
            pass
        finally:
            if target.exists():  # pragma: no cover - guard failed if reached
                target.unlink()
        self.assertFalse(swallowed, "a broad `except Exception` swallowed the ledger guard")
        self.assertFalse(target.exists())

    def test_tmp_dir_path_still_writes_and_reads_normally(self) -> None:
        # Same code path as the rest of this test class's ledger exercises,
        # confirming the guard does NOT fire for a legitimate tmp-dir path.
        ledger = CostLedger(self.path)
        total, _ = ledger.add(3.0, thresholds=[])
        self.assertAlmostEqual(total, 3.0)
        self.assertTrue(self.path.exists())
        self.assertAlmostEqual(CostLedger(self.path).total(), 3.0)


if __name__ == "__main__":
    unittest.main()
