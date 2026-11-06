"""Tests for ``scripts/tutoring/affected_tests.py`` (T00): the affected-test calculator.

The tool is exercised through its command line, against throwaway trees for the
import forms and against this repository for the two cases the plan pins
(``class_repo`` importers, ``storage_fakes`` importers). Expected sets for the
real-repository cases are derived with a regular expression over the source
text, not with the tool's own parser. No test here starts a pytest run.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "tutoring" / "affected_tests.py"
GIT = shutil.which("git") or "/usr/bin/git"

_CLASS_REPO_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+lemely\.db[ \t]+import[ \t]+[^\n#]*\bclass_repo\b"
    r"|from[ \t]+lemely\.db\.class_repo[ \t]+import\b"
    r"|import[ \t]+lemely\.db\.class_repo\b)",
    re.MULTILINE,
)
_STORAGE_FAKES_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+tests\.storage_fakes[ \t]+import\b"
    r"|from[ \t]+tests[ \t]+import[ \t]+[^\n#]*\bstorage_fakes\b"
    r"|import[ \t]+tests\.storage_fakes\b)",
    re.MULTILINE,
)


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(("TUTORING_", "GIT_"))}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv: this interpreter and the tool under test
        [sys.executable, str(TOOL), "--root", str(root), *args],
        capture_output=True,
        text=True,
        cwd=root,
        env=_clean_env(),
        timeout=120,
        check=False,
    )


def _files(proc: subprocess.CompletedProcess[str]) -> list[str]:
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, f"the list must be one line, got {proc.stdout!r}"
    return lines[0].split()


def _tree(base: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv: git against a throwaway repository
        [
            GIT,
            "-c",
            "user.name=t00",
            "-c",
            "user.email=t00@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        # The user's git config may sign commits and tags; a throwaway repository must not.
        env={**_clean_env(), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
        timeout=60,
    )


def _real_test_files() -> list[Path]:
    return sorted((ROOT / "tests").glob("**/test_*.py"))


# -- the two cases the plan pins, against this repository ----------------------


def test_direct_importer_found_for_class_repo() -> None:
    proc = _run(ROOT, "--paths", "lemely/db/class_repo.py")
    files = _files(proc)

    assert "tests/test_class_repo.py" in files
    # The plan expects about 45 direct importers on 2026-10-25.
    assert len(files) >= 40, len(files)
    assert "affected: " in proc.stderr
    assert all((ROOT / f).is_file() for f in files)

    # Independent derivation: every file whose source text imports the module
    # in a single-line form must be in the tool's answer.
    expected = {
        p.relative_to(ROOT).as_posix()
        for p in _real_test_files()
        if _CLASS_REPO_IMPORT.search(p.read_text(encoding="utf-8", errors="replace"))
    }
    assert len(expected) >= 20, len(expected)
    assert expected <= set(files), sorted(expected - set(files))[:5]


def test_storage_fakes_importers_detected() -> None:
    files = _files(_run(ROOT, "--paths", "tests/storage_fakes.py"))

    expected = {
        p.relative_to(ROOT).as_posix()
        for p in _real_test_files()
        if _STORAGE_FAKES_IMPORT.search(p.read_text(encoding="utf-8", errors="replace"))
    }
    assert len(expected) >= 8, len(expected)
    assert expected <= set(files), sorted(expected - set(files))[:5]
    assert "tests/test_purge_job.py" in files


def test_hub_change_lists_only_its_pins() -> None:
    shown = _run(ROOT, "--show-pins")
    assert shown.returncode == 0, shown.stderr
    pin_lines = [ln for ln in shown.stdout.splitlines() if ln.startswith("PIN\t")]
    hub_lines = [ln for ln in shown.stdout.splitlines() if ln.startswith("HUB\t")]
    pins = {ln.split("\t")[1] for ln in pin_lines}
    assert len(pins) == 12, pins
    assert all(len(ln.split("\t")) == 3 and ln.split("\t")[2].strip() for ln in pin_lines), (
        "every pin carries a one-line reason"
    )
    assert {ln.split("\t")[1] for ln in hub_lines} == {
        "lemely/db/models/enums.py",
        "lemely/db/models/__init__.py",
        "lemely/web/app.py",
        "lemely/web/deps.py",
        "lemely/runtime/config.py",
        "tests/conftest.py",
    }
    assert all((ROOT / pin).is_file() for pin in pins), [
        p for p in pins if not (ROOT / p).is_file()
    ]

    # Non-vacuity: enums.py has many direct importers, so a calculator that
    # expanded the hub would return far more than the pin list.
    importers = [
        p
        for p in _real_test_files()
        if re.search(
            r"lemely\.db\.models\.enums|from lemely\.db\.models import[^\n]*\bQuizKind\b",
            p.read_text(encoding="utf-8", errors="replace"),
        )
    ]
    assert len(importers) >= 50, len(importers)

    files = _files(_run(ROOT, "--paths", "lemely/db/models/enums.py"))
    assert set(files) == pins
    assert len(files) < len(importers)


def test_hub_change_lists_only_its_pins_in_a_fixture_tree(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "lemely/__init__.py": "",
            "lemely/web/__init__.py": "",
            "lemely/web/deps.py": "X = 1\n",
            "lemely/web/other.py": "Y = 1\n",
            "tests/__init__.py": "",
            "tests/test_db_schema.py": "def test_a() -> None: ...\n",
            "tests/test_uses_deps.py": "from lemely.web import deps\n",
            "tests/test_uses_other.py": "from lemely.web import other\n",
        },
    )
    assert _files(_run(root, "--paths", "lemely/web/deps.py")) == ["tests/test_db_schema.py"]
    # A hub next to an ordinary module: the hub adds only pins, the module expands.
    mixed = _files(_run(root, "--paths", "lemely/web/deps.py", "lemely/web/other.py"))
    assert mixed == ["tests/test_db_schema.py", "tests/test_uses_other.py"]


# -- import forms, against throwaway trees -------------------------------------

_BASE_TREE = {
    "lemely/__init__.py": "",
    "lemely/db/__init__.py": "",
    "lemely/db/class_repo.py": "A = 1\n",
    "lemely/db/other.py": "B = 1\n",
    "tests/__init__.py": "",
}


def test_from_package_import_module_form_detected(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            **_BASE_TREE,
            "tests/test_a.py": "from lemely.db import class_repo\n",
            "tests/test_b.py": "from lemely.db import (\n    other,\n    class_repo as cr,\n)\n",
            "tests/test_c.py": "from lemely.db import other\n",
        },
    )
    assert _files(_run(root, "--paths", "lemely/db/class_repo.py")) == [
        "tests/test_a.py",
        "tests/test_b.py",
    ]


def test_other_import_forms_detected_and_unrelated_modules_are_not(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            **_BASE_TREE,
            "tests/test_dotted.py": "import lemely.db.class_repo as m\n",
            "tests/test_from.py": "from lemely.db.class_repo import A\n",
            "tests/test_local.py": (
                "def test_x() -> None:\n    from lemely.db.class_repo import A\n    assert A\n"
            ),
            "tests/test_relative.py": "from lemely.db import class_repo\n",
            "tests/test_other.py": "from lemely.db.other import B\n",
            "tests/test_none.py": "import os\n",
        },
    )
    assert _files(_run(root, "--paths", "lemely/db/class_repo.py")) == [
        "tests/test_dotted.py",
        "tests/test_from.py",
        "tests/test_local.py",
        "tests/test_relative.py",
    ]


def test_monkeypatch_string_target_detected(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "lemely/__init__.py": "",
            "lemely/web/__init__.py": "",
            "lemely/web/routers/__init__.py": "",
            "lemely/web/routers/student.py": "def extract_answers() -> None: ...\n",
            "tests/__init__.py": "",
            "tests/test_attr.py": (
                "def test_a(monkeypatch) -> None:\n"
                '    monkeypatch.setattr("lemely.web.routers.student.extract_answers", print)\n'
            ),
            "tests/test_patch.py": 'PATCH = "lemely.web.routers.student"\n',
            "tests/test_colon.py": 'TARGET = "lemely.web.routers.student:extract_answers"\n',
            # A longer module name sharing the prefix must not match.
            "tests/test_boundary.py": 'T = "lemely.web.routers.students_other.thing"\n',
            "tests/test_plain.py": 'T = "no dotted path here"\n',
        },
    )
    assert _files(_run(root, "--paths", "lemely/web/routers/student.py")) == [
        "tests/test_attr.py",
        "tests/test_colon.py",
        "tests/test_patch.py",
    ]


def test_helper_import_forms_in_a_fixture_tree(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "lemely/__init__.py": "",
            "tests/__init__.py": "",
            "tests/storage_fakes.py": "class Fake: ...\n",
            "tests/test_absolute.py": "from tests.storage_fakes import Fake\n",
            "tests/test_package.py": "from tests import storage_fakes\n",
            "tests/test_bare.py": "from storage_fakes import Fake\n",
            "tests/test_relative.py": "from .storage_fakes import Fake\n",
            "tests/test_none.py": "from tests import other\n",
        },
    )
    assert _files(_run(root, "--paths", "tests/storage_fakes.py")) == [
        "tests/test_absolute.py",
        "tests/test_bare.py",
        "tests/test_package.py",
        "tests/test_relative.py",
    ]


def test_helper_importing_a_changed_module_propagates_to_its_importers(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            **_BASE_TREE,
            "tests/fakes.py": "from lemely.db.class_repo import A\n",
            "tests/test_via_helper.py": "from tests.fakes import A\n",
            "tests/test_unrelated.py": "import os\n",
        },
    )
    assert _files(_run(root, "--paths", "lemely/db/class_repo.py")) == ["tests/test_via_helper.py"]


def test_changed_test_files_are_listed_and_deleted_ones_are_not(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {**_BASE_TREE, "tests/test_kept.py": "import os\n", "tests/test_other.py": "import os\n"},
    )
    files = _files(
        _run(root, "--paths", "tests/test_kept.py", "tests/test_gone.py", "docs/readme.md")
    )
    assert files == ["tests/test_kept.py"]


def test_absolute_paths_inside_the_root_are_accepted(tmp_path: Path) -> None:
    root = _tree(tmp_path, {**_BASE_TREE, "tests/test_a.py": "from lemely.db import class_repo\n"})
    assert _files(_run(root, "--paths", str(root / "lemely/db/class_repo.py"))) == [
        "tests/test_a.py"
    ]


# -- modes and plumbing ---------------------------------------------------------


def test_diff_mode_reads_the_changed_files_from_git(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            **_BASE_TREE,
            "tests/test_a.py": "from lemely.db import class_repo\n",
            "tests/test_b.py": "from lemely.db import other\n",
        },
    )
    _git(root, "init", "-q")
    _git(root, "add", "--", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    (root / "lemely/db/class_repo.py").write_text("A = 2\n", encoding="utf-8")
    _git(root, "commit", "-q", "-a", "-m", "change")

    assert _files(_run(root, "--diff", "base", "HEAD")) == ["tests/test_a.py"]
    # Nothing changed between a revision and itself: an empty line, exit 0.
    empty = _run(root, "--diff", "HEAD", "HEAD")
    assert empty.returncode == 0, empty.stderr
    assert empty.stdout.strip() == ""
    assert "affected: 0" in empty.stderr


def test_run_flag_prints_the_wrapper_command_in_dry_run(tmp_path: Path) -> None:
    root = _tree(tmp_path, {**_BASE_TREE, "tests/test_a.py": "from lemely.db import class_repo\n"})
    proc = _run(root, "--paths", "lemely/db/class_repo.py", "--run", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    command_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY-RUN ")]
    assert len(command_lines) == 1, proc.stdout
    argv = shlex.split(command_lines[0].removeprefix("DRY-RUN "))
    assert argv == ["bash", str(root / "scripts/tutoring/pytest.sh"), "tests/test_a.py"]


def test_usage_errors_exit_two(tmp_path: Path) -> None:
    root = _tree(tmp_path, _BASE_TREE)
    for args in (
        (),
        ("--paths",),
        ("--diff", "only-one"),
        ("--paths", "a.py", "--diff", "x", "y"),
        ("--bogus",),
    ):
        proc = _run(root, *args)
        assert proc.returncode == 2, (args, proc.returncode, proc.stderr)
        assert "usage" in proc.stderr.lower(), (args, proc.stderr)
