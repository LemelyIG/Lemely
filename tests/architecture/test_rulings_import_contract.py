"""Proves the ruling module is structurally blind to pipeline output (#98, DA3/#52).

DA3 (``BUILD/DECISIONS.md``): "a ruling is never resolved by looking at
pipeline output." ``lemely/labelling/rulings.py`` lives inside
``lemely.labelling``, already covered by the "The blind labeller must not
depend on the correction pipeline" import-linter contract (pyproject.toml)
that ``tests/architecture/test_labeller_import_contract.py`` proves fires.
This test mirrors that one, but plants its scratch violation specifically
inside the rulings module's own package location, so a future refactor that
moves ``rulings.py`` (or narrows the contract) cannot silently drop this
guarantee without a test noticing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tests.architecture.lint_imports_lock import lint_imports_lock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRATCH_MODULE = _REPO_ROOT / "lemely" / "labelling" / "_scratch_rulings_violation.py"
_SCRATCH_MODULE_SOURCE = (
    "from __future__ import annotations\n\n"
    "from lemely.core.correction import correct_mcq_answers  # noqa: F401\n"
    "from lemely.io.correction_ai import build_ai_corrected_paper  # noqa: F401\n"
    "from lemely.core.schemas import CorrectedPaper  # noqa: F401\n"
)


def _lint_imports_command() -> str:
    script = Path(sys.executable).parent / "lint-imports"
    return str(script) if script.exists() else "lint-imports"


def test_contract_names_the_forbidden_modules_the_ruling_module_must_stay_blind_to() -> None:
    pyproject_text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "lemely.labelling" in pyproject_text
    assert "lemely.core.correction" in pyproject_text
    assert "lemely.io.correction_ai" in pyproject_text
    assert "lemely.core.schemas" in pyproject_text


def test_rulings_module_lives_inside_the_contract_scoped_package() -> None:
    rulings_module = _REPO_ROOT / "lemely" / "labelling" / "rulings.py"
    assert rulings_module.is_file()


def test_a_deliberate_violation_is_caught_and_the_real_package_stays_clean(tmp_path: Path) -> None:
    """One test, not two — deliberately.

    Under ``pytest -n auto`` (xdist), two separate test *functions* that both
    touch this same on-disk scratch path can be scheduled onto different
    worker processes and interleave: the "clean" assertion in one worker can
    observe the "dirty" scratch module a sibling worker just staged, or vice
    versa, at (mid-write / not-yet-cleaned-up) sequences the module-level
    docstring's split rightly never intended to be concurrent. Keeping the
    dirty-then-clean sequence inside one test function makes it atomic on a
    single worker regardless of scheduling, without relying on any
    ``pytest-xdist`` distribution mode.
    """
    with lint_imports_lock():
        _plant_lint_and_clean(tmp_path)


def _plant_lint_and_clean(tmp_path: Path) -> None:
    # Defensive: a prior crashed run of this test may have left the scratch
    # module behind (lint-imports does static analysis of the installed
    # package tree and cannot be pointed at a tmp_path copy of it).
    _SCRATCH_MODULE.unlink(missing_ok=True)

    staged = tmp_path / "_scratch_rulings_violation.py"
    staged.write_text(_SCRATCH_MODULE_SOURCE, encoding="utf-8")
    shutil.move(str(staged), str(_SCRATCH_MODULE))
    try:
        dirty_result = subprocess.run(
            [_lint_imports_command()],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )
        assert dirty_result.returncode != 0, (
            "expected lint-imports to fail on a deliberate rulings-module -> "
            f"correction-pipeline import, got:\n{dirty_result.stdout}\n{dirty_result.stderr}"
        )
        assert (
            "lemely.labelling._scratch_rulings_violation -> lemely.core.correction"
            in dirty_result.stdout
        )
    finally:
        _SCRATCH_MODULE.unlink(missing_ok=True)

    assert not _SCRATCH_MODULE.exists()
    clean_result = subprocess.run(
        [_lint_imports_command()],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )
    assert clean_result.returncode == 0, f"{clean_result.stdout}\n{clean_result.stderr}"
