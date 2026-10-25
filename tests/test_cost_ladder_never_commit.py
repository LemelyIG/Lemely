"""Real-split run artefacts hold student data and must stay out of commits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

GIT = shutil.which("git") or "git"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

REPO = Path(__file__).resolve().parent.parent
OUT = "BUILD/accuracy-runs/claude-c-2026-10-26"


def _ignored(path: str) -> bool:
    result = subprocess.run(  # noqa: S603
        [GIT, "check-ignore", "--no-index", "-q", path],
        cwd=REPO,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        "replies.jsonl",
        "real_results.json",
        "records.jsonl",
        "upstream_records.jsonl",
        "pin.json",
        "escalations.jsonl",
    ],
)
def test_real_run_artefacts_are_ignored(name: str) -> None:
    assert _ignored(f"{OUT}/baseline/real-1/{name}")


def test_real_run_nested_and_cache_paths_are_ignored() -> None:
    assert _ignored(f"{OUT}/archive/restart-x/cap1/real-2/replies.jsonl")
    assert _ignored(f"{OUT}/cache/baseline-real-1/gemini/k.json")


@pytest.mark.parametrize(
    "name",
    ["LADDER.md", "FLIP.md", "base.toml", "cache/baseline/gemini/k.json"],
)
def test_committed_ladder_files_stay_trackable(name: str) -> None:
    assert not _ignored(f"{OUT}/{name}")
