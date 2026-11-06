#!/usr/bin/env python3
"""Generate the pyright config that makes pyright judge THIS tree.

The shared virtualenv's editable install points at the main checkout, so a
plain ``pyright lemely`` run from a candidate export (or any other worktree)
resolves ``import lemely...`` to the main checkout's files and certifies code
it never read. The fix is the project setting ``extraPaths``, which pyright
searches before site-packages.

``[tool.pyright]`` in ``pyproject.toml`` holds repo-relative paths, which
pyright resolves against the config file's own directory. This script writes
the config to ``<root>/.omc/pyright-tutoring.json``, one directory below
``<root>``, so those paths must be rewritten. It copies ``[tool.pyright]`` and
changes only:

* ``include``: each entry rewritten relative to the config file's directory
  (``../lemely``). It must stay relative: pyright ignores an absolute
  ``include`` entry with a warning and then checks no files at all, which
  reports ``0 errors`` for any code (found when this script first used absolute
  entries; ``static.sh`` now also fails a pyright run that checked no file);
* ``venvPath`` / ``venv``: the venv linked or present at ``<root>/.venv``;
* ``extraPaths``: ``[<root>]``, ahead of any existing entry;
* each ``executionEnvironments`` entry's ``root``: made absolute. Their
  per-file rule overrides are copied unchanged.

Usage: ``python scripts/tutoring/pyright_config.py [--root DIR]``. Prints the
path of the written file; run ``pyright -p <that path>``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path(".omc") / "pyright-tutoring.json"


def _absolute(root: Path, value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else root / path)


def _relative_to(config_dir: Path, root: Path, value: str) -> str:
    return Path(os.path.relpath(_absolute(root, value), config_dir)).as_posix()


def build_config(pyright: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return ``pyright`` (the ``[tool.pyright]`` table) rewritten for ``root``."""
    config_dir = (root / CONFIG_RELATIVE).parent
    config: dict[str, Any] = copy.deepcopy(pyright)
    config["include"] = [
        _relative_to(config_dir, root, entry) for entry in pyright.get("include", ["lemely"])
    ]
    config["venvPath"] = str(root)
    config["venv"] = pyright.get("venv", ".venv")
    config["extraPaths"] = [str(root), *(_absolute(root, p) for p in pyright.get("extraPaths", []))]
    environments = config.get("executionEnvironments", [])
    for environment in environments:
        environment["root"] = _absolute(root, environment["root"])
    return config


def write_config(root: Path) -> Path:
    """Write the generated config for ``root`` and return its path."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"no pyproject.toml in {root}")
    table = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("pyright")
    if not isinstance(table, dict):
        raise ValueError(f"{pyproject} has no [tool.pyright] table")
    out = root / CONFIG_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_config(table, root), indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="tree root holding pyproject.toml (default: the tree this script lives in)",
    )
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    try:
        out = write_config(root)
    except (FileNotFoundError, ValueError) as err:
        sys.stderr.write(f"pyright_config.py: {err}\n")
        return 1
    sys.stdout.write(f"{out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
