"""Filesystem layout for one paper's labels (spec §6).

Every path is keyed by both ``paper_id`` and ``labeller_id`` so that two
distinct labellers labelling the same paper never overwrite each other
(spec §6; anticipates DA2/#51's 10% re-mark by a second labeller).

``paper_id`` / ``labeller_id`` / scan-image ``name`` values reach these
functions straight from an HTTP query string (see
:mod:`lemely.labelling.server`), so every one of them is validated against a
strict identifier pattern and every resulting path is checked to still be
inside its expected subtree before being handed back — belt and braces
against path traversal (e.g. ``paper_id=../../../../tmp/evil``).
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_EVAL_ROOT = Path("eval")

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class InvalidIdentifierError(ValueError):
    """Raised when a paper_id, labeller_id, or scan-image name fails validation."""


def _validate_identifier(value: str, *, kind: str) -> str:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise InvalidIdentifierError(f"invalid {kind}: {value!r}")
    return value


def _require_within(candidate: Path, root: Path) -> Path:
    """Resolve ``candidate`` and confirm it did not escape ``root``."""
    resolved = candidate.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise InvalidIdentifierError(f"path {candidate} escapes {root}")
    return resolved


def label_dir(paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    _validate_identifier(paper_id, kind="paper_id")
    _validate_identifier(labeller_id, kind="labeller_id")
    labels_root = eval_root / "labels"
    return _require_within(labels_root / paper_id / labeller_id, labels_root)


def transcription_path(
    paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT
) -> Path:
    return label_dir(paper_id, labeller_id, eval_root) / "transcription.jsonl"


def marking_path(paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    return label_dir(paper_id, labeller_id, eval_root) / "marking.jsonl"


def manifest_path(paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    return label_dir(paper_id, labeller_id, eval_root) / "manifest.json"


def scan_dir(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    """Scan-region image data for ``paper_id`` (pass 1 only — no mark scheme lives here)."""
    _validate_identifier(paper_id, kind="paper_id")
    scans_root = eval_root / "scans"
    return _require_within(scans_root / paper_id, scans_root)


def scan_image_path(paper_id: str, name: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    """One scan-region image file for ``paper_id``, identified by its basename ``name``."""
    _validate_identifier(name, kind="scan image name")
    directory = scan_dir(paper_id, eval_root)
    return _require_within(directory / name, directory)


def mark_scheme_path(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    """The already-parsed mark scheme JSON for ``paper_id`` (pass 2 only)."""
    _validate_identifier(paper_id, kind="paper_id")
    schemes_root = eval_root / "mark_schemes"
    return _require_within(schemes_root / f"{paper_id}.json", schemes_root)
