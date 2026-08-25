"""A cross-process lock for tests that shell out to ``lint-imports`` (#98).

``lint-imports`` statically analyses the **real** installed package tree, so
a test that proves a contract fires has to plant its deliberate violation
inside ``lemely/`` itself — there is no way to point the linter at a
``tmp_path`` copy. That makes the package tree shared mutable state.

Under ``pytest -n auto`` those tests land on different worker processes and
interleave: while one worker has its scratch violation staged,
``test_import_linter.py::test_all_contracts_pass`` on another worker runs
``lint-imports`` against the same tree, sees the planted violation, and fails
with a contract break that has nothing to do with the code under test. The
symptom is an import-linter failure reporting one more file than the tree
really has (``Analyzed 218 files`` against a clean 217).

Every test that invokes ``lint-imports`` — planter or reader — must hold this
lock for the whole of its run. The lock is advisory ``flock`` on a file in
the repo's scratch directory, so it works across processes without a new
dependency, and it is released automatically if a worker dies.

This hazard predates #98: ``test_labeller_import_contract.py`` already
planted into the same tree. #98 added a second planter, which is what made
the collision frequent enough to turn a gate red.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK_PATH = _REPO_ROOT / "reports" / ".scratch" / "lint-imports.lock"


@contextmanager
def lint_imports_lock() -> Iterator[None]:
    """Serialise ``lint-imports`` invocations across xdist workers."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK_PATH.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
