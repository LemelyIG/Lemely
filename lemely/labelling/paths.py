"""Filesystem layout for one paper's labels (spec §6).

Every path is keyed by both ``paper_id`` and ``labeller_id`` so that two
distinct labellers labelling the same paper never overwrite each other
(spec §6; anticipates DA2/#51's 10% re-mark by a second labeller).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_EVAL_ROOT = Path("eval")


def label_dir(paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    return eval_root / "labels" / paper_id / labeller_id


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
    return eval_root / "scans" / paper_id


def mark_scheme_path(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> Path:
    """The already-parsed mark scheme JSON for ``paper_id`` (pass 2 only)."""
    return eval_root / "mark_schemes" / f"{paper_id}.json"
