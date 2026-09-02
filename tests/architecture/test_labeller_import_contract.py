"""Proves the "labeller must stay blind" import-linter contract actually fires (#46).

Declaring the contract in pyproject.toml is not enough on its own — this
test plants a scratch module inside ``lemely.labelling`` that deliberately
imports the correction pipeline and asserts ``lint-imports`` reports the
violation, then removes the scratch module.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tests.architecture.lint_imports_lock import lint_imports_lock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRATCH_MODULE = _REPO_ROOT / "lemely" / "labelling" / "_scratch_violation.py"
_SCRATCH_MODULE_SOURCE = (
    "from __future__ import annotations\n\n"
    "from lemely.core.correction import correct_mcq_answers  # noqa: F401\n"
)


def _lint_imports_command() -> str:
    script = Path(sys.executable).parent / "lint-imports"
    return str(script) if script.exists() else "lint-imports"


def test_contract_is_declared_for_the_labeller_module() -> None:
    pyproject_text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "lemely.labelling" in pyproject_text
    assert "lemely.core.correction" in pyproject_text
    assert "lemely.io.correction_ai" in pyproject_text


def test_a_deliberate_violation_inside_labelling_is_caught(tmp_path: Path) -> None:
    # The lock is held across plant -> lint -> unplant: the scratch module
    # lives in the real package tree, so any sibling xdist worker running
    # lint-imports meanwhile would see this violation as its own failure.
    with lint_imports_lock():
        _run_deliberate_violation_check(tmp_path)


def _run_deliberate_violation_check(tmp_path: Path) -> None:
    # Defensive: a prior crashed run of this test may have left the scratch
    # module behind (it lives inside the real package, since lint-imports
    # does static analysis of the installed package tree and cannot be
    # pointed at a tmp_path copy of it).
    _SCRATCH_MODULE.unlink(missing_ok=True)

    # Stage the content under pytest's managed tmp_path, then move it into
    # place with a single atomic rename — minimises the window in which a
    # half-written or leftover file could sit in the live source tree.
    staged = tmp_path / "_scratch_violation.py"
    staged.write_text(_SCRATCH_MODULE_SOURCE, encoding="utf-8")
    shutil.move(str(staged), str(_SCRATCH_MODULE))
    try:
        result = subprocess.run(
            [_lint_imports_command()],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )
        assert result.returncode != 0, (
            "expected lint-imports to fail on a deliberate labeller -> "
            f"correction-pipeline import, got:\n{result.stdout}\n{result.stderr}"
        )
        assert "lemely.labelling._scratch_violation -> lemely.core.correction" in result.stdout
    finally:
        _SCRATCH_MODULE.unlink(missing_ok=True)


def test_the_real_labelling_package_passes_the_contract_clean() -> None:
    with lint_imports_lock():
        assert not _SCRATCH_MODULE.exists()
        result = subprocess.run(
            [_lint_imports_command()],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
