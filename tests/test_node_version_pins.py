"""One Node version everywhere: ``.nvmrc`` is the source of truth.

CI once ran Node 22 while developers ran Node 26, and tests that passed locally failed in CI
(Node 26 has a ``sessionStorage`` global, Node 22 does not). Every workflow reads ``.nvmrc``,
and the web Dockerfile, which cannot read it, must name the same major version.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NODE_MAJOR = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))


def _setup_node_steps() -> list[tuple[str, dict[str, object]]]:
    steps: list[tuple[str, dict[str, object]]] = []
    for path in WORKFLOWS:
        jobs = yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs", {})
        for job_name, job in jobs.items():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/setup-node@"):
                    steps.append((f"{path.name}:{job_name}", step.get("with") or {}))
    return steps


def test_nvmrc_is_a_bare_major_version() -> None:
    assert re.fullmatch(r"\d+", NODE_MAJOR), (
        f".nvmrc should hold a major version, got {NODE_MAJOR!r}"
    )


def test_every_setup_node_step_reads_nvmrc() -> None:
    steps = _setup_node_steps()
    assert steps, "expected at least one actions/setup-node step"
    for where, with_ in steps:
        assert with_.get("node-version-file") == ".nvmrc", (
            f"{where} must use node-version-file: .nvmrc"
        )
        assert "node-version" not in with_, f"{where} hard-codes node-version"


def test_web_dockerfile_matches_nvmrc() -> None:
    dockerfile = (ROOT / "web/Dockerfile").read_text(encoding="utf-8")
    images = re.findall(r"^FROM node:(\d+)", dockerfile, flags=re.MULTILINE)
    assert images, "web/Dockerfile has no node base image"
    assert set(images) == {NODE_MAJOR}, (
        f"web/Dockerfile uses node:{images}, .nvmrc says {NODE_MAJOR}"
    )
