"""Tests for the T00 execution tooling: ``scripts/tutoring/*.sh`` and ``pyright_config.py``.

These cover refusal paths, dry-run output and pure helpers only. No test here
starts a pytest run, a live-stack run, or reaches a real database: every script
that could do so is either refused before it acts, run with ``TUTORING_DRY_RUN``,
or pointed at a fake binary that records its arguments.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "tutoring"
BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "/usr/bin/git"

SHELL_SCRIPTS = (
    "pytest.sh",
    "scan_py.sh",
    "race.sh",
    "static.sh",
    "precommit.sh",
    "export.sh",
    "gate_db.sh",
    "live_lock.sh",
    "live_e2e.sh",
    "live_audit.sh",
    "affected.sh",
)

# The source-scanning alternation of the plan's SCAN-PY, split so that this file
# does not itself contain a match for it.
_SCAN_RE = re.compile("rglob" + r"\(|LEMELY" + "_SRC|ast" + r"\.parse")
_THIS_LANE_TESTS = {
    "tests/test_tutoring_tooling.py",
    "tests/test_tutoring_affected_tests.py",
    "tests/test_tutoring_app_helper.py",
}
_GATE_DB = "lemely_tutoring_gate"
_MAINTENANCE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


# -- helpers --------------------------------------------------------------------


def _env(extra: dict[str, str] | None = None, path_prefix: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TUTORING_", "GIT_"))}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra or {})
    return env


def _run(
    script: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv: bash running a script under test
        [BASH, str(script), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env if env is not None else _env(),
        timeout=120,
        check=False,
    )


def _script(name: str, *args: str, cwd: Path, env: dict[str, str] | None = None):
    return _run(SCRIPTS / name, *args, cwd=cwd, env=env)


def _fake_bin(base: Path, *names: str, stdout: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Create fake executables that append ``<name> <args>`` to a log and exit 0."""
    bindir = base / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = base / "calls.log"
    for name in names:
        body = f'#!{BASH}\necho "{name} $*" >> "{log}"\n'
        if stdout and name in stdout:
            body += f"printf '%s\\n' {shlex.quote(stdout[name])}\n"
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    return bindir, log


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
        env={**_env(), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
        timeout=60,
    )


def _dry_run_argv(stdout: str) -> list[str]:
    lines = [ln for ln in stdout.splitlines() if ln.startswith("DRY-RUN ")]
    assert len(lines) == 1, stdout
    return shlex.split(lines[0].removeprefix("DRY-RUN "))


# -- the scripts exist and are well formed -------------------------------------


def test_every_planned_script_exists_parses_and_fails_closed(tmp_path: Path) -> None:
    assert len(SHELL_SCRIPTS) == 11
    for name in SHELL_SCRIPTS:
        path = SCRIPTS / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text, name
        assert "BASH_SOURCE" in text, f"{name} must locate its own tree root"
        syntax = subprocess.run(  # noqa: S603 - fixed argv
            [BASH, "-n", str(path)], capture_output=True, text=True, cwd=tmp_path, check=False
        )
        assert syntax.returncode == 0, (name, syntax.stderr)
    for helper in ("affected_tests.py", "pyright_config.py"):
        assert (SCRIPTS / helper).is_file(), helper


# -- pytest.sh ------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("tests",),
        ("tests/",),
        ("./tests",),
        ("tests/architecture",),
        ("README.md",),
        ("tests/does_not_exist.py",),
        ("tests/../pyproject.toml",),
        ("scripts/tutoring/affected_tests.py",),
        ("/etc/passwd",),
        ("-k", "something"),
        ("--cov=lemely", "tests/test_tutoring_tooling.py"),
        ("--rootdir=/", "tests/test_tutoring_tooling.py"),
        ("-c", "other.ini", "tests/test_tutoring_tooling.py"),
        ("--", "tests/test_tutoring_tooling.py"),
    ],
    ids=lambda a: " ".join(a) or "no-arguments",
)
def test_pytest_wrapper_refuses_no_args_directory_and_tests(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    proc = _script("pytest.sh", *args, cwd=tmp_path)
    assert proc.returncode != 0, proc.stdout
    assert "refus" in proc.stderr.lower(), proc.stderr
    # Refused before it printed lemely.__file__ or started anything.
    assert proc.stdout == ""


def test_pytest_wrapper_dry_run_prints_the_pinned_command(tmp_path: Path) -> None:
    target = "tests/test_tutoring_tooling.py"
    env = _env({"TUTORING_DRY_RUN": "1"})
    for arg in (target, f"{target}::test_x", str(ROOT / target)):
        proc = _script("pytest.sh", "-x", "-k", "dry and run", arg, cwd=tmp_path, env=env)
        assert proc.returncode == 0, proc.stderr
        argv = _dry_run_argv(proc.stdout)
        assert argv[0] == str(ROOT / ".venv/bin/python")
        assert argv[1:3] == ["-m", "pytest"]
        assert "--no-cov" in argv
        assert argv[argv.index("-p") + 1] == "no:cacheprovider"
        assert "-rs" in argv
        assert argv[argv.index("-k") + 1] == "dry and run"
        # Absolute paths inside the tree are normalised to tree-relative ones.
        assert argv[-1] == arg.removeprefix(f"{ROOT}/")


# -- scan_py.sh -----------------------------------------------------------------


def test_scan_py_finds_at_least_ten_files(tmp_path: Path) -> None:
    proc = _script("scan_py.sh", "--list", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    listed = [ln for ln in proc.stdout.splitlines() if ln.startswith("tests/")]
    assert len(listed) >= 10, listed

    independent = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "tests").glob("**/test_*.py")
        if _SCAN_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    }
    assert set(listed) == independent
    assert len(listed) == len(set(listed))
    assert not (_THIS_LANE_TESTS & set(listed))


def test_scan_py_refuses_when_it_finds_fewer_than_the_minimum(tmp_path: Path) -> None:
    env = _env({"TUTORING_SCAN_MIN": "100000", "TUTORING_DRY_RUN": "1"})
    for args in (("--list",), ()):
        proc = _script("scan_py.sh", *args, cwd=tmp_path, env=env)
        assert proc.returncode != 0
        assert "fewer than" in proc.stderr
        assert "DRY-RUN" not in proc.stdout


def test_scan_py_runs_the_list_through_the_pytest_wrapper(tmp_path: Path) -> None:
    proc = _script("scan_py.sh", cwd=tmp_path, env=_env({"TUTORING_DRY_RUN": "1"}))
    assert proc.returncode == 0, proc.stderr
    argv = _dry_run_argv(proc.stdout)
    files = [a for a in argv if a.startswith("tests/")]
    assert len(files) >= 10
    assert "--no-cov" in argv


# -- race.sh --------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("5",),
        ("0", "tests/test_tutoring_tooling.py"),
        ("-1", "tests/test_tutoring_tooling.py"),
        ("abc", "tests/test_tutoring_tooling.py"),
        ("21", "tests/test_tutoring_tooling.py"),
        ("3", "tests"),
        ("3", "tests/does_not_exist.py"),
    ],
    ids=lambda a: " ".join(a) or "no-arguments",
)
def test_race_refuses_bad_counts_and_unusable_files(tmp_path: Path, args: tuple[str, ...]) -> None:
    proc = _script("race.sh", *args, cwd=tmp_path, env=_env({"TUTORING_DRY_RUN": "1"}))
    assert proc.returncode != 0
    assert "refus" in proc.stderr.lower(), proc.stderr
    assert "DRY-RUN" not in proc.stdout


def test_race_runs_the_files_n_times_through_the_wrapper(tmp_path: Path) -> None:
    proc = _script(
        "race.sh",
        "3",
        "tests/test_tutoring_tooling.py",
        cwd=tmp_path,
        env=_env({"TUTORING_DRY_RUN": "1"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert re.findall(r"race iteration (\d+)/3", proc.stdout) == ["1", "2", "3"]
    assert proc.stdout.count("DRY-RUN") == 3


# -- static.sh ------------------------------------------------------------------


def test_static_dry_run_lists_every_ci_step_and_the_pyright_override(tmp_path: Path) -> None:
    proc = _script("static.sh", cwd=tmp_path, env=_env({"TUTORING_DRY_RUN": "1"}))
    assert proc.returncode == 0, proc.stderr
    steps = dict(
        line.removeprefix("STEP ").split("\t", 1)
        for line in proc.stdout.splitlines()
        if line.startswith("STEP ")
    )
    assert list(steps) == [
        "ruff-check",
        "ruff-format",
        "mypy",
        "pyright",
        "import-linter",
        "review-rate-gate",
    ]
    assert steps["ruff-check"].endswith("ruff check .")
    assert steps["ruff-format"].endswith("ruff format --check .")
    assert steps["mypy"].endswith("mypy lemely")
    assert "pyright_config.py" in steps["pyright"]
    assert ".omc/pyright-tutoring.json" in steps["pyright"]
    assert steps["import-linter"].endswith("lint-imports")
    assert steps["review-rate-gate"].endswith("check_review_rate_gate.py")


def test_static_only_selects_one_step_and_refuses_unknown_names(tmp_path: Path) -> None:
    env = _env({"TUTORING_DRY_RUN": "1"})
    one = _script("static.sh", "--only", "pyright", cwd=tmp_path, env=env)
    assert one.returncode == 0, one.stderr
    assert [ln.split("\t")[0] for ln in one.stdout.splitlines() if ln.startswith("STEP ")] == [
        "STEP pyright"
    ]
    for args in (("--only", "eslint"), ("--only",), ("--what",)):
        bad = _script("static.sh", *args, cwd=tmp_path, env=env)
        assert bad.returncode != 0
        assert "refus" in bad.stderr.lower(), bad.stderr


# -- pyright_config.py ----------------------------------------------------------


def test_pyright_config_adds_extra_paths_and_absolute_roots(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    shutil.copy(ROOT / "pyproject.toml", tree / "pyproject.toml")
    proc = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and the tool under test
        [sys.executable, str(SCRIPTS / "pyright_config.py"), "--root", str(tree)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_env(),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = tree / ".omc" / "pyright-tutoring.json"
    assert proc.stdout.strip() == str(out)
    config = json.loads(out.read_text(encoding="utf-8"))

    source = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pyright"]
    source_envs = source["executionEnvironments"]
    assert len(source_envs) >= 10, "the source config must have execution environments to convert"

    assert config["extraPaths"] == [str(tree)]
    # Relative to the config file: pyright ignores an absolute include entry and
    # then checks no file at all, reporting "0 errors" for anything.
    assert config["include"] == ["../lemely"]
    assert not any(os.path.isabs(entry) for entry in config["include"])
    assert (out.parent / config["include"][0]).resolve() == (tree / "lemely").resolve()
    assert config["venvPath"] == str(tree)
    assert config["venv"] == ".venv"
    assert len(config["executionEnvironments"]) == len(source_envs)
    for original, converted in zip(source_envs, config["executionEnvironments"], strict=True):
        assert os.path.isabs(converted["root"])
        assert converted["root"] == str(tree / original["root"])
        # Everything but the root (the per-file rule overrides) is copied unchanged.
        assert {k: v for k, v in converted.items() if k != "root"} == {
            k: v for k, v in original.items() if k != "root"
        }
    # Top-level rule settings other than the path keys survive.
    carried = {
        k for k in source if k not in {"venvPath", "venv", "include", "executionEnvironments"}
    }
    assert carried <= set(config)


def test_pyright_config_refuses_a_tree_without_pyproject(tmp_path: Path) -> None:
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(SCRIPTS / "pyright_config.py"), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_env(),
        timeout=60,
        check=False,
    )
    assert proc.returncode != 0
    assert "pyproject.toml" in proc.stderr


@pytest.mark.parametrize(
    ("pyright_output", "pyright_exit", "expected_exit", "expected_word"),
    [
        ("0 errors, 0 warnings, 0 informations\nTotal files checked: 0", 0, 1, "FAIL"),
        ("0 errors, 0 warnings, 0 informations", 0, 1, "FAIL"),
        ("0 errors, 0 warnings, 0 informations\nTotal files checked: 12", 0, 0, "PASS"),
        ("3 errors, 0 warnings, 0 informations\nTotal files checked: 12", 1, 1, "FAIL"),
    ],
    ids=["zero-files", "no-stats-line", "clean", "errors"],
)
def test_static_pyright_step_never_passes_a_run_that_checked_no_files(
    tmp_path: Path,
    pyright_output: str,
    pyright_exit: int,
    expected_exit: int,
    expected_word: str,
) -> None:
    tree = tmp_path / "tree"
    (tree / "scripts" / "tutoring").mkdir(parents=True)
    for name in ("static.sh", "pyright_config.py"):
        shutil.copy(SCRIPTS / name, tree / "scripts" / "tutoring" / name)
    shutil.copy(ROOT / "pyproject.toml", tree / "pyproject.toml")
    (tree / ".venv").symlink_to(ROOT / ".venv")
    fake = _fake_python(tmp_path, pyright_output, pyright_exit)

    proc = _run(
        tree / "scripts" / "tutoring" / "static.sh",
        "--only",
        "pyright",
        cwd=tmp_path,
        env=_env({"TUTORING_PYRIGHT": str(fake)}),
    )
    assert proc.returncode == expected_exit, (proc.stdout, proc.stderr)
    assert f"{expected_word} pyright" in proc.stdout
    logged = (tmp_path / "python.log").read_text(encoding="utf-8")
    assert f"-p {tree}/.omc/pyright-tutoring.json --stats" in logged
    if expected_word == "FAIL" and "Total files checked: 12" not in pyright_output:
        assert "checked no files" in proc.stdout


# -- export.sh ------------------------------------------------------------------


def test_export_command_paths_exclude_reports(tmp_path: Path) -> None:
    plain = _script("export.sh", "--print-paths", cwd=tmp_path)
    assert plain.returncode == 0, plain.stderr
    paths = plain.stdout.split()
    assert paths == [
        "lemely",
        "tests",
        "corpus",
        "scripts",
        "pyproject.toml",
        "alembic.ini",
        "docs/tutoring/SPEC.md",
        # Not in the plan's list, but the review-rate gate (a STATIC step) fails without it.
        "BUILD/review-rate-baseline.json",
        # The settings drift tests and test_tutoring_config read it from the tree root.
        "lemely.toml.example",
    ]
    assert not [p for p in paths if "reports" in p]
    assert all((ROOT / p).exists() for p in paths), [p for p in paths if not (ROOT / p).exists()]

    with_web = _script("export.sh", "--print-paths", "--web", cwd=tmp_path)
    assert with_web.returncode == 0, with_web.stderr
    # web/ plus the repo-root files its unit tests read (designDocs, ciCopyGate).
    web_extra = ["web", "DESIGN.md", "docs/design-canvas-notes.md", ".github/workflows/ci.yml"]
    assert with_web.stdout.split() == [*paths, *web_extra]
    assert all((ROOT / p).exists() for p in web_extra), [
        p for p in web_extra if not (ROOT / p).exists()
    ]


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A throwaway git repository holding a copy of ``export.sh`` and a tiny tree."""
    repo = tmp_path / "repo"
    (repo / "scripts" / "tutoring").mkdir(parents=True)
    shutil.copy(SCRIPTS / "export.sh", repo / "scripts" / "tutoring" / "export.sh")
    files = {
        "lemely/__init__.py": "",
        "lemely/mod.py": "original\n",
        "tests/test_a.py": "x\n",
        "corpus/data.txt": "c\n",
        "scripts/other.py": "s\n",
        "pyproject.toml": "[project]\nname = 'x'\n",
        "alembic.ini": "[alembic]\n",
        "docs/tutoring/SPEC.md": "# spec\n",
        "BUILD/review-rate-baseline.json": "{}\n",
        "lemely.toml.example": "# example\n",
        "reports/huge.json": "{}\n",
        "web/package.json": "{}\n",
        "DESIGN.md": "# design\n",
        "docs/design-canvas-notes.md": "# notes\n",
        ".github/workflows/ci.yml": "name: ci\n",
    }
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "--", *files, "scripts/tutoring/export.sh")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / "web" / "node_modules" / "pkg").mkdir(parents=True)
    return repo


def _export(repo: Path, tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None):
    env = _env(
        {"TUTORING_EXPORTS_DIR": str(tmp_path / "exports"), "TUTORING_MIN_FREE_GIB": "0"}
        | (extra_env or {})
    )
    return _run(repo / "scripts" / "tutoring" / "export.sh", *args, cwd=tmp_path, env=env)


def test_export_copies_head_overlay_and_links_without_reports(
    mini_repo: Path, tmp_path: Path
) -> None:
    (mini_repo / "lemely" / "mod.py").write_text("changed\n", encoding="utf-8")
    (mini_repo / "lemely" / "pkg").mkdir()
    (mini_repo / "lemely" / "pkg" / "new.py").write_text("new\n", encoding="utf-8")
    (mini_repo / "web" / "src").mkdir()
    (mini_repo / "web" / "src" / "x.ts").write_text("export {}\n", encoding="utf-8")

    proc = _export(
        mini_repo,
        tmp_path,
        "e1",
        "HEAD",
        "--web",
        "--overlay",
        "lemely/mod.py",
        "lemely/pkg/new.py",
        "web/src/x.ts",
        "--delete",
        "tests/test_a.py",
    )
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "exports" / "e1"
    assert proc.stdout.splitlines()[0] == str(out)
    assert any("size" in ln for ln in proc.stdout.splitlines()), proc.stdout

    assert (out / "lemely/mod.py").read_text(encoding="utf-8") == "changed\n"
    assert (out / "lemely/pkg/new.py").read_text(encoding="utf-8") == "new\n"
    assert (out / "web/src/x.ts").is_file()
    assert not (out / "tests/test_a.py").exists()
    assert (out / "corpus/data.txt").is_file()
    assert (out / "docs/tutoring/SPEC.md").is_file()
    assert (out / "BUILD/review-rate-baseline.json").is_file()
    assert not (out / "reports").exists()
    assert (out / "web/package.json").is_file()
    assert (out / ".venv").is_symlink()
    assert (out / ".venv").resolve() == (mini_repo / ".venv").resolve()
    assert (out / "web/node_modules").is_symlink()
    assert (out / "web/node_modules").resolve() == (mini_repo / "web/node_modules").resolve()


def test_export_without_web_leaves_web_out(mini_repo: Path, tmp_path: Path) -> None:
    proc = _export(mini_repo, tmp_path, "e2", "HEAD")
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "exports" / "e2"
    assert (out / "lemely/mod.py").read_text(encoding="utf-8") == "original\n"
    assert not (out / "web").exists()
    assert (out / ".venv").is_symlink()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("../escape", "HEAD"), "name"),
        (("bad name", "HEAD"), "name"),
        (("-rf", "HEAD"), "name"),
        (("ok1", "no-such-revision"), "revision"),
        (("ok2", "HEAD", "--overlay", "does/not/exist.py"), "overlay"),
        (("ok3", "HEAD", "--overlay", "/etc/passwd"), "overlay"),
        (("ok4", "HEAD", "--overlay", "../outside.py"), "overlay"),
        (("ok5", "HEAD", "--overlay", "web/package.json"), "--web"),
        (("ok6", "HEAD", "--delete", "../outside.py"), "delete"),
        (("ok7", "HEAD", "--delete", "tests"), "delete"),
        (("ok8", "HEAD", "--overlay"), "overlay"),
        (("ok9",), "usage"),
        (("ok10", "HEAD", "--unknown"), "usage"),
    ],
)
def test_export_refuses_bad_input_without_creating_anything(
    mini_repo: Path, tmp_path: Path, args: tuple[str, ...], message: str
) -> None:
    proc = _export(mini_repo, tmp_path, *args)
    assert proc.returncode != 0
    assert message in proc.stderr.lower() or message in proc.stderr, proc.stderr
    exports = tmp_path / "exports"
    assert not exports.exists() or list(exports.iterdir()) == []


def test_export_refuses_an_existing_name_and_low_disk(mini_repo: Path, tmp_path: Path) -> None:
    first = _export(mini_repo, tmp_path, "dup", "HEAD")
    assert first.returncode == 0, first.stderr
    again = _export(mini_repo, tmp_path, "dup", "HEAD")
    assert again.returncode != 0
    assert "already exists" in again.stderr

    low = _export(
        mini_repo, tmp_path, "low", "HEAD", extra_env={"TUTORING_MIN_FREE_GIB": "999999999"}
    )
    assert low.returncode != 0
    assert "free" in low.stderr
    assert not (tmp_path / "exports" / "low").exists()


# -- gate_db.sh -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "postgres",
        "lemely_test_abc123",
        "lemely_mig_1",
        "lemely_tutoring_e2e",
        "lemely_tutoring_gate2",
        "",
        "lemely_tutoring_gate; DROP DATABASE postgres",
    ],
)
def test_gate_db_refuses_other_database_names(tmp_path: Path, name: str) -> None:
    fakebin, log = _fake_bin(tmp_path, "psql")
    env = _env({"TUTORING_GATE_DB": name}, path_prefix=fakebin)
    for sub in ("reset", "upgrade", "heads"):
        proc = _script("gate_db.sh", sub, cwd=tmp_path, env=env)
        assert proc.returncode != 0, (sub, proc.stdout)
        assert "refus" in proc.stderr.lower(), proc.stderr
    assert not log.exists(), "a refused database name must not reach psql"


def test_gate_db_refuses_unknown_subcommands_and_unsafe_revisions(tmp_path: Path) -> None:
    fakebin, log = _fake_bin(tmp_path, "psql")
    env = _env(path_prefix=fakebin)
    for args in (
        (),
        ("drop",),
        ("downgrade",),
        ("downgrade", "; ls"),
        ("downgrade", "a b"),
        ("reset", "x"),
    ):
        proc = _script("gate_db.sh", *args, cwd=tmp_path, env=env)
        assert proc.returncode != 0, args
        assert "refus" in proc.stderr.lower(), (args, proc.stderr)
    assert not log.exists()


def test_gate_db_reset_only_touches_the_gate_database(tmp_path: Path) -> None:
    fakebin, log = _fake_bin(tmp_path, "psql")
    proc = _script("gate_db.sh", "reset", cwd=tmp_path, env=_env(path_prefix=fakebin))
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1, calls
    call = calls[0]
    assert _MAINTENANCE_URL in call
    statements = re.findall(r"(?:DROP|CREATE) DATABASE (?:IF EXISTS )?(\w+)", call)
    assert statements == [_GATE_DB, _GATE_DB], call


def _fake_python(base: Path, output: str, exit_code: int = 0) -> Path:
    path = base / "fakepython"
    log = base / "python.log"
    path.write_text(
        f'#!{BASH}\necho "$* url=$LEMELY_DATABASE__URL path=$PYTHONPATH" >> "{log}"\n'
        f"printf '%s\\n' {shlex.quote(output)}\nexit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_gate_db_heads_demands_exactly_one_head(tmp_path: Path) -> None:
    one = _fake_python(tmp_path, "0043_merge_heads (head)")
    ok = _script("gate_db.sh", "heads", cwd=tmp_path, env=_env({"TUTORING_PY": str(one)}))
    assert ok.returncode == 0, ok.stderr
    logged = (tmp_path / "python.log").read_text(encoding="utf-8")
    assert "-m alembic heads" in logged
    assert f"/{_GATE_DB} " in logged
    assert f"path={ROOT}" in logged

    two = _fake_python(tmp_path, "0050_a (head)\n0049_b (head)")
    bad = _script("gate_db.sh", "heads", cwd=tmp_path, env=_env({"TUTORING_PY": str(two)}))
    assert bad.returncode != 0
    assert "exactly one" in bad.stderr


def test_gate_db_check_is_informational(tmp_path: Path) -> None:
    failing = _fake_python(tmp_path, "FAILED: New upgrade operations detected", exit_code=255)
    proc = _script("gate_db.sh", "check", cwd=tmp_path, env=_env({"TUTORING_PY": str(failing)}))
    assert proc.returncode == 0, proc.stderr
    assert "informational" in proc.stdout
    assert "255" in proc.stdout


# -- precommit.sh ---------------------------------------------------------------


@pytest.fixture
def precommit_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "pcrepo"
    (repo / "scripts" / "tutoring").mkdir(parents=True)
    shutil.copy(SCRIPTS / "precommit.sh", repo / "scripts" / "tutoring" / "precommit.sh")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "init", "-q")
    return repo


def _precommit(repo: Path, *args: str, dry: bool = True, extra: dict[str, str] | None = None):
    env = _env(({"TUTORING_DRY_RUN": "1"} if dry else {}) | (extra or {}))
    return _run(repo / "scripts" / "tutoring" / "precommit.sh", *args, cwd=repo.parent, env=env)


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--files",),
        ("--files", "missing.py"),
        ("--all-files", "a.py"),
        ("--files", "a.py", "--all-files"),
        ("--bogus",),
        ("a.py",),
    ],
    ids=lambda a: " ".join(a) or "no-arguments",
)
def test_precommit_refuses_bad_invocations(precommit_repo: Path, args: tuple[str, ...]) -> None:
    proc = _precommit(precommit_repo, *args)
    assert proc.returncode != 0
    assert "refus" in proc.stderr.lower(), proc.stderr
    assert "DRY-RUN" not in proc.stdout


def test_precommit_files_mode_skips_the_three_whole_package_hooks(precommit_repo: Path) -> None:
    proc = _precommit(precommit_repo, "--files", "a.py", "b.py", "gone.py")
    assert proc.returncode == 0, proc.stderr
    assert "gone.py" in proc.stderr, "a path that does not exist is skipped with a warning"
    argv = _dry_run_argv(proc.stdout)
    assert argv[0] == "env"
    assert "SKIP=mypy,pyright,import-linter" in argv
    assert argv[2].endswith("/.venv/bin/pre-commit")
    assert argv[argv.index("run") :] == ["run", "--files", "a.py", "b.py"]


def test_precommit_all_files_skips_pyright_and_runs_the_pyright_step_after(
    precommit_repo: Path,
) -> None:
    proc = _precommit(precommit_repo, "--all-files")
    assert proc.returncode == 0, proc.stderr
    argv = _dry_run_argv(proc.stdout)
    assert "SKIP=pyright" in argv
    assert argv[argv.index("run") :] == ["run", "--all-files"]
    follow_up = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY-RUN-NEXT ")]
    assert len(follow_up) == 1, proc.stdout
    assert shlex.split(follow_up[0].removeprefix("DRY-RUN-NEXT "))[-2:] == ["--only", "pyright"]


def test_precommit_refuses_outside_a_git_work_tree(tmp_path: Path) -> None:
    bare = tmp_path / "plain"
    (bare / "scripts" / "tutoring").mkdir(parents=True)
    shutil.copy(SCRIPTS / "precommit.sh", bare / "scripts" / "tutoring" / "precommit.sh")
    (bare / "a.py").write_text("x = 1\n", encoding="utf-8")
    env = _env({"TUTORING_DRY_RUN": "1", "GIT_CEILING_DIRECTORIES": str(tmp_path)})
    proc = _run(
        bare / "scripts" / "tutoring" / "precommit.sh", "--files", "a.py", cwd=tmp_path, env=env
    )
    assert proc.returncode != 0
    assert "git work tree" in proc.stderr


# -- live_lock.sh, live_e2e.sh, live_audit.sh ------------------------------------


def _lock_env(lock: Path, extra: dict[str, str] | None = None, path_prefix: Path | None = None):
    return _env({"TUTORING_LIVE_LOCK": str(lock)} | (extra or {}), path_prefix=path_prefix)


def test_live_lock_is_exclusive_and_owner_checked(tmp_path: Path) -> None:
    lock = tmp_path / "state" / "live.lock"
    env = _lock_env(lock)

    free = _script("live_lock.sh", "status", cwd=tmp_path, env=env)
    assert free.returncode == 0 and free.stdout.startswith("free"), free.stdout

    first = _script("live_lock.sh", "acquire", "ownerA", cwd=tmp_path, env=env)
    assert first.returncode == 0, first.stderr
    assert (lock / "owner").read_text(encoding="utf-8").strip() == "ownerA"
    assert (lock / "worktree").read_text(encoding="utf-8").strip() == os.path.realpath(ROOT)
    assert (lock / "acquired_at").read_text(encoding="utf-8").strip()

    second = _script("live_lock.sh", "acquire", "ownerB", cwd=tmp_path, env=env)
    assert second.returncode != 0
    assert "ownerA" in second.stderr

    wrong = _script("live_lock.sh", "release", "ownerB", cwd=tmp_path, env=env)
    assert wrong.returncode != 0
    assert lock.is_dir(), "a release by another owner must leave the lock in place"

    held = _script("live_lock.sh", "status", cwd=tmp_path, env=env)
    assert held.returncode == 0 and held.stdout.startswith("held") and "ownerA" in held.stdout

    done = _script("live_lock.sh", "release", "ownerA", cwd=tmp_path, env=env)
    assert done.returncode == 0, done.stderr
    assert not lock.exists()
    assert _script("live_lock.sh", "release", "ownerA", cwd=tmp_path, env=env).returncode != 0


def test_live_lock_refuses_bad_usage(tmp_path: Path) -> None:
    env = _lock_env(tmp_path / "live.lock")
    for args in ((), ("acquire",), ("acquire", "bad owner"), ("release",), ("steal", "x")):
        proc = _script("live_lock.sh", *args, cwd=tmp_path, env=env)
        assert proc.returncode != 0, args
        assert "refus" in proc.stderr.lower(), (args, proc.stderr)


_LIVE_CALLS = (
    ("live_e2e.sh", "dedicated", "e2e/tutoring-smoke.spec.ts"),
    ("live_e2e.sh", "shared", "e2e/tutoring-smoke.spec.ts"),
    ("live_audit.sh", "dedicated"),
    ("live_audit.sh", "shared"),
)


@pytest.mark.parametrize("call", _LIVE_CALLS, ids=lambda c: " ".join(c))
def test_live_scripts_refuse_without_lock(tmp_path: Path, call: tuple[str, ...]) -> None:
    fakebin, log = _fake_bin(tmp_path, "npm", "psql", "ss", "supabase")
    env = _lock_env(tmp_path / "absent.lock", path_prefix=fakebin)
    proc = _script(*call, cwd=tmp_path, env=env)
    assert proc.returncode != 0
    assert "lock" in proc.stderr.lower(), proc.stderr
    assert not log.exists(), "nothing may run before the lock is verified"


@pytest.mark.parametrize("call", _LIVE_CALLS, ids=lambda c: " ".join(c))
def test_live_scripts_refuse_a_lock_held_for_another_worktree(
    tmp_path: Path, call: tuple[str, ...]
) -> None:
    lock = tmp_path / "other.lock"
    lock.mkdir()
    (lock / "owner").write_text("someone\n", encoding="utf-8")
    (lock / "worktree").write_text("/somewhere/else\n", encoding="utf-8")
    fakebin, log = _fake_bin(tmp_path, "npm", "psql", "ss", "supabase")
    proc = _script(*call, cwd=tmp_path, env=_lock_env(lock, path_prefix=fakebin))
    assert proc.returncode != 0
    assert "worktree" in proc.stderr.lower(), proc.stderr
    assert not log.exists()


@pytest.mark.parametrize("script", ["live_e2e.sh", "live_audit.sh"])
def test_live_scripts_refuse_an_unknown_database_mode(tmp_path: Path, script: str) -> None:
    fakebin, log = _fake_bin(tmp_path, "npm", "psql", "ss", "supabase")
    proc = _script(
        script,
        "staging",
        "e2e/tutoring-smoke.spec.ts",
        cwd=tmp_path,
        env=_lock_env(tmp_path / "absent.lock", path_prefix=fakebin),
    )
    assert proc.returncode != 0
    assert "mode" in proc.stderr.lower(), proc.stderr
    assert not log.exists()


@pytest.mark.parametrize("port", ["8000", "5173"])
def test_live_e2e_refuses_when_a_dev_port_is_already_listening(tmp_path: Path, port: str) -> None:
    lock = tmp_path / "mine.lock"
    lock.mkdir()
    (lock / "owner").write_text("me\n", encoding="utf-8")
    (lock / "worktree").write_text(f"{os.path.realpath(ROOT)}\n", encoding="utf-8")
    listing = (
        "State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
        f"LISTEN 0      511    127.0.0.1:{port}   0.0.0.0:*"
    )
    fakebin, log = _fake_bin(tmp_path, "npm", "psql", "ss", stdout={"ss": listing})
    proc = _script(
        "live_e2e.sh",
        "dedicated",
        "e2e/tutoring-smoke.spec.ts",
        cwd=tmp_path,
        env=_lock_env(lock, path_prefix=fakebin),
    )
    assert proc.returncode != 0
    assert port in proc.stderr, proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls and all(c.startswith("ss ") for c in calls), calls


def test_live_audit_delegates_to_the_one_live_runner() -> None:
    text = (SCRIPTS / "live_audit.sh").read_text(encoding="utf-8")
    assert "live_e2e.sh" in text and "--audit" in text
    runner = (SCRIPTS / "live_e2e.sh").read_text(encoding="utf-8")
    assert "run audit" in runner and "check_ui_gates.py" in runner
    assert "run test:e2e" in runner


# -- affected.sh ----------------------------------------------------------------


def test_affected_wrapper_forwards_to_the_calculator(tmp_path: Path) -> None:
    proc = _script("affected.sh", "--show-pins", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("PIN\t") == 12
