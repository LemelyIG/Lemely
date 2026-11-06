#!/usr/bin/env python3
"""Affected-test calculator for the tutoring build (PLAN section 0.7, AFFECTED).

Given the files a change touched, list the test files that can break, using the
standard-library ``ast`` module (not tokensave, whose index serves another
branch, and not grep, which the tokensave hook denies for symbol-shaped
patterns on code files).

A test file under ``tests/`` is affected when it

* imports a changed ``lemely`` module or a changed test helper, in any form:
  ``import a.b``, ``from a import b`` (``b`` a submodule), ``from a.b import c``,
  a relative import inside the ``tests`` package, or, for a helper such as
  ``tests/storage_fakes.py``, ``from tests.x import`` and the bare ``from x import``;
* names a changed ``lemely`` module in a string literal, which is how
  ``monkeypatch.setattr("lemely.web.routers.student.extract_answers", ...)``
  and ``mock.patch("lemely.x.y")`` reach their target (the dotted name must match
  on module boundaries, so ``student`` does not match ``students_other``);
* is itself one of the changed files.

A helper under ``tests/`` that imports a changed module makes the helper
changed too, so the tests that import the helper are listed as well (one
closure over the helpers; ``tests/conftest.py`` is excluded from it, see below).

Hubs. A few modules are imported, directly or through fixtures, by so many tests
that expanding them lists most of the suite (``lemely/db/models/enums.py`` has
about 115 direct test importers). A changed hub contributes only the PINS: a
short list of tests that exercise the hub's contract, each with a one-line
reason. CI's full run covers the rest; the lead reads the hub list in
PLAN section 4 before relying on a local sample.

Usage::

    python scripts/tutoring/affected_tests.py --paths lemely/db/class_repo.py
    python scripts/tutoring/affected_tests.py --diff tutoring/pre-W2 HEAD [--run]
    python scripts/tutoring/affected_tests.py --show-pins

Prints the files, space-separated on one line, to stdout and ``affected: N ...``
to stderr. ``--run`` runs the list through ``scripts/tutoring/pytest.sh``;
``--dry-run`` prints that command instead. Exit status 2 is a usage error.
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]

# Modules whose change lists only PINS (PLAN section 0.7). Each is imported by,
# or wired into, so many tests that expansion is noise; CI runs the rest.
HUBS: dict[str, str] = {
    "lemely/db/models/enums.py": "about 115 direct test importers; every enum change lands here",
    "lemely/db/models/__init__.py": "re-exports every model; imported by most database tests",
    "lemely/web/app.py": "the app factory; every web test builds it",
    "lemely/web/deps.py": "dependency providers every web test overrides or resolves",
    "lemely/runtime/config.py": "the Settings model every layer reads",
    "tests/conftest.py": "fixtures shared by the whole suite",
}

# Tests pinned for any hub change, each with the reason it is a good sentinel.
PINS: dict[str, str] = {
    "tests/test_db_schema.py": "schema and enum drift: models, constraints and indexes",
    "tests/test_enums_marking_detail.py": "enum member sets the marking detail depends on",
    "tests/test_notification_repo.py": "notification type enum and the repository over it",
    "tests/test_notification_prefs_repo.py": "preference mirrors of the notification types",
    "tests/test_me_router.py": "the /api/me routes and the preference API",
    "tests/test_web_app.py": "app factory wiring and router mounting",
    "tests/test_runtime_config.py": "the Settings model and its validation",
    "tests/test_settings_example_drift.py": "lemely.toml.example against the Settings model",
    "tests/test_cli_doctor.py": "doctor reads Settings and the app wiring",
    "tests/test_scheduled_notifications.py": "the sweeper reads notification enums and deps",
    "tests/test_authz_matrix_complete.py": "every route declared with the guard actually wired",
    "tests/test_authz_matrix.py": "the authz matrix against the real guards",
}

_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_MAX_STRING = 20_000


@dataclass(frozen=True)
class ModuleInfo:
    """What one parsed test or helper file imports and names."""

    imports: frozenset[str]
    name_prefixes: frozenset[str]


def module_name(rel: str) -> str:
    """Dotted module name for a repository-relative ``.py`` path."""
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_package(rel: str) -> bool:
    return rel.endswith("/__init__.py")


def _resolve(current: str, is_package: bool, level: int, module: str | None) -> str | None:
    """Absolute dotted name of ``from <dots><module> import ...`` inside ``current``."""
    if level == 0:
        return module
    package = current.split(".") if is_package else current.split(".")[:-1]
    if level - 1 > len(package):
        return None
    base = package[: len(package) - (level - 1)]
    if module:
        base = [*base, *module.split(".")]
    return ".".join(base) if base else None


def parse_file(path: Path, rel: str) -> ModuleInfo | None:
    """Parse ``path``; ``None`` if it is not valid Python."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None
    current = module_name(rel)
    is_package = _is_package(rel)
    imports: set[str] = set()
    prefixes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(current, is_package, node.level, node.module)
            if base is None:
                continue
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) <= _MAX_STRING
        ):
            for token in _DOTTED.findall(node.value):
                parts = token.split(".")
                prefixes.update(".".join(parts[: i + 1]) for i in range(len(parts)))
    return ModuleInfo(frozenset(imports), frozenset(prefixes))


def _is_test_file(rel: str) -> bool:
    return rel.startswith("tests/") and Path(rel).name.startswith("test_") and rel.endswith(".py")


def _is_helper(rel: str) -> bool:
    name = Path(rel).name
    return (
        rel.startswith("tests/")
        and rel.endswith(".py")
        and not name.startswith("test_")
        and name not in {"__init__.py", "conftest.py"}
    )


def _aliases(rel: str) -> set[str]:
    """Names a module can be imported by: its dotted path and, for a helper, its bare name."""
    names = {module_name(rel)}
    if _is_helper(rel):
        names.add(Path(rel).stem)
    return names


def normalise(root: Path, raw: str) -> str | None:
    """Repository-relative POSIX path for ``raw``; ``None`` if it is outside ``root``."""
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
    cleaned = path.as_posix()
    return cleaned[2:] if cleaned.startswith("./") else cleaned


@dataclass(frozen=True)
class Result:
    """The answer for one set of changed paths."""

    files: list[str]
    hubs: list[str]
    ignored: list[str]
    unparsed: list[str]


def affected(root: Path, changed: list[str]) -> Result:
    """Compute the affected test files for ``changed`` (repository-relative paths)."""
    universe: dict[str, ModuleInfo] = {}
    unparsed: list[str] = []
    for path in sorted((root / "tests").glob("**/*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts:
            continue
        info = parse_file(path, rel)
        if info is None:
            unparsed.append(rel)
        else:
            universe[rel] = info

    result: set[str] = set()
    hubs: list[str] = []
    ignored: list[str] = []
    lemely_modules: set[str] = set()
    targets: set[str] = set()
    for rel in changed:
        if rel in HUBS:
            hubs.append(rel)
            result.update(pin for pin in PINS if (root / pin).is_file())
        elif _is_test_file(rel):
            if (root / rel).is_file():
                result.add(rel)
            else:
                ignored.append(rel)
        elif rel.startswith("lemely/") and rel.endswith(".py"):
            lemely_modules.add(module_name(rel))
            targets.update(_aliases(rel))
        elif _is_helper(rel):
            if (root / rel).is_file():
                targets.update(_aliases(rel))
            else:
                ignored.append(rel)
        else:
            ignored.append(rel)

    # Close over the helpers: a helper importing a target is itself a target.
    helpers = {rel: info for rel, info in universe.items() if _is_helper(rel)}
    grown = True
    while grown:
        grown = False
        for rel, info in helpers.items():
            if info.imports & targets and not _aliases(rel) <= targets:
                targets.update(_aliases(rel))
                grown = True

    for rel, info in universe.items():
        if not _is_test_file(rel):
            continue
        if info.imports & targets or any(m in info.name_prefixes for m in lemely_modules):
            result.add(rel)

    return Result(sorted(result), sorted(hubs), sorted(ignored), sorted(unparsed))


def _git_changed(root: Path, base: str, head: str) -> list[str]:
    proc = subprocess.run(  # noqa: S603 - fixed argv; revisions are passed as arguments
        ["git", "-C", str(root), "diff", "--name-only", base, head, "--"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"affected_tests.py: git diff {base} {head} failed: {proc.stderr.strip()}\n"
        )
        raise SystemExit(1)
    return [line for line in proc.stdout.splitlines() if line]


def _show_pins() -> None:
    for path, reason in HUBS.items():
        sys.stdout.write(f"HUB\t{path}\t{reason}\n")
    for path, reason in PINS.items():
        sys.stdout.write(f"PIN\t{path}\t{reason}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="affected_tests.py",
        description="List the test files a change can break (imports and string targets).",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--paths", nargs="+", metavar="FILE", help="changed files")
    mode.add_argument("--diff", nargs=2, metavar=("BASE", "HEAD"), help="files changed between")
    mode.add_argument("--show-pins", action="store_true", help="print the hubs and their pins")
    parser.add_argument("--run", action="store_true", help="run the list with pytest.sh")
    parser.add_argument("--dry-run", action="store_true", help="with --run, print the command")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()

    if args.show_pins:
        _show_pins()
        return 0

    raw = list(args.paths) if args.paths else _git_changed(root, args.diff[0], args.diff[1])
    changed: list[str] = []
    for item in raw:
        rel = normalise(root, item)
        if rel is None:
            sys.stderr.write(f"affected_tests.py: ignoring {item} (outside {root})\n")
        else:
            changed.append(rel)

    result = affected(root, changed)
    sys.stdout.write(" ".join(result.files) + "\n")
    notes = [f"{len(changed)} changed paths"]
    if result.hubs:
        notes.append(f"hub only pinned: {', '.join(result.hubs)}")
    if result.ignored:
        notes.append(f"{len(result.ignored)} not python modules or tests")
    if result.unparsed:
        notes.append(
            f"{len(result.unparsed)} test files did not parse: {', '.join(result.unparsed)}"
        )
    sys.stderr.write(f"affected: {len(result.files)} test files ({'; '.join(notes)})\n")

    if args.run:
        if not result.files:
            sys.stderr.write("affected_tests.py: nothing to run\n")
            return 0
        command = ["bash", str(root / "scripts/tutoring/pytest.sh"), *result.files]
        if args.dry_run:
            sys.stdout.write(f"DRY-RUN {shlex.join(command)}\n")
            return 0
        return subprocess.run(command, cwd=root, check=False).returncode  # noqa: S603
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
