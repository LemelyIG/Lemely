"""Test-touch ledger: the M0.7a split-mechanism gate (spec §3.3, §4, §7).

Per DA1 (issue #31 scope clarification, recorded in ``BUILD/DECISIONS.md``):
this module gates evaluation *joins* — pairing a pipeline result with a
``split == "test"`` label — not file access. Labelling reads of test-split
papers, scans, and mark schemes (``eval/labels/`` handling code, #46/#47)
stay ungated; do not add a token requirement there.

``authorize_test_split_join`` is the single sanctioned call site for
comparing a label's ``split`` to ``"test"``. A static-source scan
(``tests/eval/test_test_touch_static_guard.py``) fails CI if that
comparison appears anywhere else under ``lemely/`` or ``scripts/``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.eval.manifest import Split

# Name of the environment variable holding the authorisation token — not a
# credential itself.
_TOKEN_ENV_VAR = "LEMELY_TEST_SPLIT_TOKEN"  # noqa: S105

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = _REPO_ROOT / "reports" / "accuracy" / "test-touch-ledger.jsonl"


class TestSplitAccessError(Exception):
    """Raised when a caller attempts an unauthorised test-split join.

    Specifically: an evaluation join against the test split without a valid
    authorisation token.
    """

    # Not a pytest test case — the name coincidentally starts with "Test"
    # because it names the thing it gates (the test split), not a test.
    __test__ = False


def authorize_test_split_join(
    split: Split,
    *,
    token: str | None,
    run_id: str,
    caller: str,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """Gate an evaluation-result/label join against ``split``.

    No-op for ``split in ("train", "dev")``: no token required, no ledger
    entry written. For ``split == "test"``, requires ``token`` to match the
    ``LEMELY_TEST_SPLIT_TOKEN`` environment variable, raising
    :class:`TestSplitAccessError` when it is absent or does not match. Every
    authorised call appends exactly one entry to the append-only
    ``ledger_path`` JSONL file.
    """
    if split != "test":
        return

    expected_token = os.environ.get(_TOKEN_ENV_VAR)
    if not expected_token or token != expected_token:
        raise TestSplitAccessError(
            f"caller={caller!r} attempted a test-split evaluation join for "
            f"run_id={run_id!r} without a valid {_TOKEN_ENV_VAR} token."
        )

    _append_ledger_entry(ledger_path, run_id=run_id, caller=caller)


def _append_ledger_entry(ledger_path: Path, *, run_id: str, caller: str) -> None:
    entry = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "caller": caller,
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
