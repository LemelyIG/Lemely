"""``deploy.yml``'s IndexNow job: production only, after a good deploy, and never red.

Staging URLs must never be submitted, a failed deploy must not be masked, and a best-effort ping
must not be able to fail the pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
JOBS: dict[str, Any] = yaml.safe_load(TEXT)["jobs"]
JOB: dict[str, Any] = JOBS["indexnow"]


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def test_runs_for_production_only() -> None:
    condition = str(JOB["if"])
    assert "needs.resolve-env.outputs.environment == 'production'" in condition
    assert "staging" not in condition
    assert "resolve-env" in _needs(JOB)


def test_runs_only_after_a_successful_frontend_deploy_and_smoke_test() -> None:
    assert {"deploy-frontend", "smoke-test"} <= _needs(JOB)
    # An `if` that names always()/failure()/cancelled() would run it after a failed deploy.
    for token in ("always()", "failure()", "cancelled()", "!cancelled"):
        assert token not in str(JOB["if"])


def test_cannot_fail_the_workflow() -> None:
    assert JOB["continue-on-error"] is True
    assert "continue-on-error" not in {k for step in JOB["steps"] for k in step}


def test_no_other_job_waits_for_it() -> None:
    for name, job in JOBS.items():
        assert "indexnow" not in _needs(job), name


def test_checks_out_history_and_runs_the_script_with_a_read_only_token() -> None:
    checkout = next(
        s for s in JOB["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0
    submit = next(s for s in JOB["steps"] if s.get("id") == "submit")
    assert "scripts/indexnow_submit.py" in submit["run"]
    assert "--force" not in submit["run"]  # the path filter must stay in force
    assert JOB["permissions"] == {"contents": "read", "actions": "read"}
    assert "secrets." not in yaml.safe_dump(JOB)  # the key is public; no secret reaches the job


def test_the_marker_is_recorded_only_after_an_accepted_submission() -> None:
    marker = [s for s in JOB["steps"] if "upload-artifact" in str(s.get("uses", ""))]
    assert len(marker) == 1
    assert marker[0]["if"] == "steps.submit.outputs.submitted == 'true'"
    assert marker[0]["with"]["name"] == "frontend-submitted-${{ github.sha }}"
    assert marker[0]["with"]["overwrite"] is True  # a same-SHA redeploy must not 409


def test_the_script_and_the_workflow_agree_on_the_marker_name() -> None:
    script = (ROOT / "scripts/indexnow_submit.py").read_text(encoding="utf-8")
    assert 'MARKER_PREFIX: Final = "frontend-submitted-"' in script
