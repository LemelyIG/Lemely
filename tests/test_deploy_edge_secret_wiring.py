"""``deploy.yml``'s edge-secret wiring: the Worker gets its secret BEFORE any backend rollout.

If a backend revision that enforces ``LEMELY_EDGE__ORIGIN_SECRET`` took traffic while the Worker
still sent no secret, every waitlist call would be refused. So the push is its own job, both
deploy jobs wait for it, and the previous (rotation) value reaches the backend too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
JOBS: dict[str, Any] = yaml.safe_load(TEXT)["jobs"]


def _needs(job: str) -> set[str]:
    needs = JOBS[job].get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _ancestors(job: str) -> set[str]:
    seen: set[str] = set()
    stack = list(_needs(job))
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(_needs(current))
    return seen


def test_both_deploy_jobs_wait_for_the_edge_secret_job() -> None:
    assert "edge-secret" in _ancestors("deploy-backend")
    assert "edge-secret" in _ancestors("deploy-frontend")


def test_the_edge_secret_job_does_not_wait_for_either_deploy() -> None:
    ancestors = _ancestors("edge-secret")
    assert "deploy-backend" not in ancestors
    assert "deploy-frontend" not in ancestors


def test_the_worker_secret_is_pushed_in_that_job_only() -> None:
    steps = {step.get("name"): step for step in JOBS["edge-secret"]["steps"]}
    push = steps["Push Worker edge secret"]
    assert "wrangler" in push["run"] and "secret put ORIGIN_SECRET" in push["run"]
    assert push["env"]["EDGE_ORIGIN_SECRET"] == "${{ secrets.EDGE_ORIGIN_SECRET }}"
    assert "$EDGE_ORIGIN_SECRET" in push["run"]
    assert TEXT.count("secret put ORIGIN_SECRET") == 1  # not also in deploy-frontend
    frontend_names = [step.get("name") for step in JOBS["deploy-frontend"]["steps"]]
    assert "Push Worker edge secret" not in frontend_names


def test_an_empty_edge_secret_skips_the_push_instead_of_setting_an_empty_one() -> None:
    run = {s.get("name"): s for s in JOBS["edge-secret"]["steps"]}["Push Worker edge secret"]["run"]
    skip = run.index('-z "$EDGE_ORIGIN_SECRET"')
    assert skip < run.index("secret put")
    assert "exit 0" in run[skip : run.index("secret put")]


def test_the_backend_gets_the_current_and_the_previous_secret() -> None:
    deploy = next(s for s in JOBS["deploy-backend"]["steps"] if "env_vars" in s.get("with", {}))
    lines = deploy["with"]["env_vars"].splitlines()
    assert "LEMELY_EDGE__ORIGIN_SECRET=${{ secrets.EDGE_ORIGIN_SECRET }}" in lines
    assert "LEMELY_EDGE__ORIGIN_SECRET_PREVIOUS=${{ secrets.EDGE_ORIGIN_SECRET_PREVIOUS }}" in lines
