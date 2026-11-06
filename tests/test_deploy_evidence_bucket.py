"""The tutor evidence bucket is per environment, project-owned and private (SC-22).

GCS bucket names are one global namespace. The settings default
``lemely-tutor-evidence`` is a placeholder that no Lemely project owns, so a
deploy relying on it would send every tutor's ID and qualification scans to
whoever creates that bucket first, and that person could replace a stored file
so the admin's signed link (A2) serves a file Lemely never checked.

Two files decide the deployed name: ``.github/workflows/deploy.yml`` sets it and
``scripts/gcp-bootstrap.sh`` creates the bucket. These tests read both and check
that they name the same bucket for each environment, that the name is never the
default and never shared between environments, and that the script creates the
bucket private and grants the runtime account access to that bucket only.

A private bucket can still be a stranger's: whoever registers the name first
can enforce both settings and grant our runtime account access. So the backend
also requires the bucket's owning project number to equal
``LEMELY_STORAGE__GCS_PROJECT_NUMBER`` (review finding 3), which deploy.yml
derives from the workload identity provider's resource name, and the deploy job
checks the bucket's privacy and owner itself after the rollout (finding 5).
Both workflow steps are executed here with bash, the second against a fake
``gcloud`` and ``curl``, so these tests judge what the steps do, not their text.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from lemely.runtime.config import StorageSettings

_ROOT = Path(__file__).resolve().parent.parent
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_BOOTSTRAP = _ROOT / "scripts" / "gcp-bootstrap.sh"
_PROJECT = "proj-1234"
_EVIDENCE_VAR = "LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET"
_NUMBER_VAR = "LEMELY_STORAGE__GCS_PROJECT_NUMBER"
_OTHER_BUCKET_VARS = ("LEMELY_STORAGE__BUCKET", "LEMELY_STORAGE__AVATAR_BUCKET")
_NUMBER = "123456789012"
_PROVIDER = (
    f"projects/{_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-lemely"
)
_STEP_OUTPUT = re.compile(
    r"^\$\{\{\s*steps\.(?P<id>[A-Za-z0-9_-]+)\.outputs\.(?P<output>[A-Za-z0-9_]+)\s*\}\}$"
)

# The one shape deploy.yml gives every bucket name: an optional per-environment
# override variable, else a name formatted from the project id and environment.
_BUCKET_EXPRESSION = re.compile(
    r"^\$\{\{\s*vars\.(?P<override>[A-Z_]+)\s*\|\|\s*"
    r"format\('(?P<template>[^']+)',\s*vars\.GCP_PROJECT_ID,\s*"
    r"needs\.resolve-env\.outputs\.environment\)\s*\}\}$"
)


def _environments() -> list[str]:
    """The environments the workflow can deploy, read from its dispatch input."""
    workflow = yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    options: list[str] = workflow[True]["workflow_dispatch"]["inputs"]["environment"]["options"]
    return options


def _deploy_steps() -> list[dict[str, Any]]:
    """The steps of the ``deploy-backend`` job, in order."""
    workflow = yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = workflow["jobs"]["deploy-backend"]["steps"]
    return steps


def _deploy_env_vars() -> dict[str, str]:
    """The ``env_vars`` block of the Cloud Run deploy step, as name -> expression."""
    deploy = next(step for step in _deploy_steps() if step.get("id") == "deploy")
    pairs = (line.split("=", 1) for line in deploy["with"]["env_vars"].splitlines() if line)
    return {name: value for name, value in pairs}


def _step_index(step_id: str) -> int:
    return next(i for i, step in enumerate(_deploy_steps()) if step.get("id") == step_id)


def _run_step(
    step: Mapping[str, Any], env: Mapping[str, str], tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run one ``run:`` step the way a GitHub-hosted runner does, with ``env``.

    The runner's default shell is ``bash --noprofile --norc -eo pipefail {0}``.
    Returns the process and what the step wrote to ``$GITHUB_OUTPUT``.
    """
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    bash = shutil.which("bash")
    assert bash is not None
    process = subprocess.run(  # noqa: S603 - fixed argv: bash and this repo's workflow step
        [bash, "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env={"PATH": os.environ["PATH"], **env, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    written = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if line
    )
    return process, written


def _render(expression: str, environment: str, overrides: Mapping[str, str]) -> str:
    """Evaluate one bucket expression the way GitHub Actions does.

    An unset ``vars.`` reference renders as the empty string, which ``||``
    treats as false, so the formatted fallback is used.
    """
    match = _BUCKET_EXPRESSION.match(expression)
    assert match, f"unexpected bucket expression in deploy.yml: {expression}"
    return overrides.get(match["override"]) or match["template"].format(_PROJECT, environment)


def _environment_loop() -> tuple[list[str], str]:
    """The script's per-environment loop: its environments and its body.

    Line continuations are joined first, so one command reads as one line.
    """
    text = _BOOTSTRAP.read_text(encoding="utf-8").replace("\\\n", " ")
    match = re.search(r"^for ENV in (?P<envs>[^;]+); do\n(?P<body>.*?)^done$", text, re.M | re.S)
    assert match, "gcp-bootstrap.sh has no top-level `for ENV in ...; do ... done` loop"
    return match["envs"].split(), match["body"]


def _shell_assignments(body: str) -> dict[str, str]:
    return dict(re.findall(r'^\s*([A-Z_]+)="([^"]*)"\s*$', body, re.M))


def _expand(value: str, environment: str) -> str:
    return value.replace("${PROJECT_ID}", _PROJECT).replace("${ENV}", environment)


def _bootstrap_evidence_buckets() -> dict[str, str]:
    environments, body = _environment_loop()
    assignments = _shell_assignments(body)
    assert "EVIDENCE_BUCKET" in assignments, "gcp-bootstrap.sh names no evidence bucket"
    template = assignments["EVIDENCE_BUCKET"]
    return {env: _expand(template, env) for env in environments}


def _commands(body: str, needle: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if needle in line]


def test_deploy_sets_per_environment_tutor_evidence_bucket() -> None:
    environments = _environments()
    assert environments == ["staging", "production"]
    env_vars = _deploy_env_vars()
    # The backend that refuses the default name is the one the pipeline deploys.
    assert env_vars["LEMELY_STORAGE__BACKEND"] == "gcs"
    assert _EVIDENCE_VAR in env_vars, "deploy.yml does not set the evidence bucket"
    expression = env_vars[_EVIDENCE_VAR]
    names = {env: _render(expression, env, {}) for env in environments}
    other_buckets = {
        _render(env_vars[var], env, {}) for var in _OTHER_BUCKET_VARS for env in environments
    }
    assert len(other_buckets) == 4

    # One bucket per environment: a shared one would let a staging test read or
    # overwrite a real tutor's documents.
    assert len(set(names.values())) == len(environments)
    default = StorageSettings().tutor_evidence_bucket
    for env, name in names.items():
        assert name != default
        assert name.startswith(f"{_PROJECT}-"), "the name must be scoped to the project id"
        assert name.endswith(f"-{env}")
        assert name not in other_buckets
    # The bucket the workflow points at is the one the bootstrap script creates.
    assert names == _bootstrap_evidence_buckets()

    # An override (Settings > Environments) is honoured per environment and is
    # its own variable, never one of the other buckets' overrides.
    override = _BUCKET_EXPRESSION.match(expression)
    assert override is not None
    other_overrides = {
        m["override"]
        for var in _OTHER_BUCKET_VARS
        if (m := _BUCKET_EXPRESSION.match(env_vars[var])) is not None
    }
    assert len(other_overrides) == 2
    assert override["override"] not in other_overrides
    assert _render(expression, "staging", {override["override"]: "own-bucket"}) == "own-bucket"


def test_gcp_bootstrap_creates_private_evidence_bucket() -> None:
    environments, body = _environment_loop()
    assert environments == _environments()
    names = _bootstrap_evidence_buckets()
    assert len(names) == 2
    default = StorageSettings().tutor_evidence_bucket
    assert default not in names.values()
    assert len(set(names.values())) == len(environments)

    # Created the way the uploads and avatars buckets are: inside the same loop,
    # with uniform bucket-level access and public access prevention, and an
    # objectAdmin binding for this environment's runtime account on that bucket.
    loop = re.search(
        r"^\s*for BUCKET in (?P<items>[^;]+); do\n(?P<body>.*?)^\s*done$", body, re.M | re.S
    )
    assert loop, "no `for BUCKET in ...; do ... done` loop in the environment loop"
    items = loop["items"].split()
    assert items == ['"$UPLOADS_BUCKET"', '"$AVATAR_BUCKET"', '"$EVIDENCE_BUCKET"']
    (create,) = _commands(loop["body"], "gcloud storage buckets create")
    assert '"gs://$BUCKET"' in create.split()
    assert {"--uniform-bucket-level-access", "--public-access-prevention"} <= set(create.split())
    (grant,) = _commands(loop["body"], "add-iam-policy-binding")
    assert '"gs://$BUCKET"' in grant.split()
    assert '--member="serviceAccount:${RUNTIME_SA}"' in grant.split()
    assert '--role="roles/storage.objectAdmin"' in grant.split()

    # A bucket made by hand before this script knew about it is brought to the
    # same state: both settings are enforced on every run, not only on create.
    evidence_updates = [
        command.split()
        for command in _commands(body, "gcloud storage buckets update")
        if '"gs://$EVIDENCE_BUCKET"' in command.split()
    ]
    assert len(evidence_updates) == 1
    assert {"--uniform-bucket-level-access", "--public-access-prevention"} <= set(
        evidence_updates[0]
    )

    # The backend reads the bucket's settings before first use (SC-22), which
    # needs storage.buckets.get on that bucket. objectAdmin does not include it.
    # The deploy job reads the same settings after the rollout (finding 5) as the
    # deployer account, so that account gets the same read on this bucket, and
    # on no other bucket.
    def _grant(command: list[str]) -> tuple[str, str]:
        member = next(a for a in command if a.startswith("--member="))
        role = next(a for a in command if a.startswith("--role="))
        return member, role

    evidence_grants = {
        _grant(command.split())
        for command in _commands(body, "add-iam-policy-binding")
        if '"gs://$EVIDENCE_BUCKET"' in command.split()
    }
    assert evidence_grants == {
        ('--member="serviceAccount:${RUNTIME_SA}"', '--role="roles/storage.legacyBucketReader"'),
        ('--member="serviceAccount:${SA_EMAIL}"', '--role="roles/storage.legacyBucketReader"'),
    }
    deployer_grants = [c for c in _commands(body, "add-iam-policy-binding") if "${SA_EMAIL}" in c]
    assert len(deployer_grants) == 1
    # ${SA_EMAIL} is the account deploy.yml authenticates as (GCP_SERVICE_ACCOUNT).
    bootstrap_text = _BOOTSTRAP.read_text(encoding="utf-8")
    assert re.search(r"^\s*GCP_SERVICE_ACCOUNT\s+= \$\{SA_EMAIL\}$", bootstrap_text, re.M)

    # Documents are kept until an admin or the tutor deletes them: the 90-day
    # delete rule stays on the uploads bucket alone.
    (lifecycle,) = _commands(body, "--lifecycle-file")
    assert '"gs://$UPLOADS_BUCKET"' in lifecycle.split()

    # Never a project-level storage role: access is per bucket.
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    project_roles = re.search(r"^for ROLE in (?P<roles>[^;]+); do$", text, re.M)
    assert project_roles
    assert len(project_roles["roles"].split()) == 3
    assert not any(role.startswith("roles/storage.") for role in project_roles["roles"].split())


def _project_number_step() -> tuple[dict[str, Any], str, str]:
    """The step that derives the project number: ``(step, provider env name, output name)``.

    Found through the deploy step's own ``LEMELY_STORAGE__GCS_PROJECT_NUMBER`` reference,
    and its provider input through the expression the auth step uses, so the test follows
    the workflow's wiring instead of assuming step or variable names.
    """
    env_vars = _deploy_env_vars()
    assert _NUMBER_VAR in env_vars, "deploy.yml does not set the project number"
    reference = _STEP_OUTPUT.match(env_vars[_NUMBER_VAR])
    assert reference, f"{_NUMBER_VAR} is not a step output: {env_vars[_NUMBER_VAR]}"
    steps = _deploy_steps()
    step = steps[_step_index(reference["id"])]
    auth = next(
        s for s in steps if str(s.get("uses", "")).startswith("google-github-actions/auth@")
    )
    provider_expression = auth["with"]["workload_identity_provider"]
    names = [name for name, value in step.get("env", {}).items() if value == provider_expression]
    assert len(names) == 1, "the step does not read the auth step's workload identity provider"
    return step, names[0], reference["output"]


def test_deploy_sets_the_project_number_for_both_environments(tmp_path: Path) -> None:
    """Finding 3: the backend compares the evidence bucket's owner with this number.

    Derived before the rollout, on every run of the job (no condition), from the
    workload identity provider's resource name, which google-github-actions/auth
    requires in its full ``projects/<number>/...`` form. One project hosts both
    environments (gcp-bootstrap.sh creates staging and production in one
    PROJECT_ID), so one number serves both.
    """
    step, provider_env, output = _project_number_step()
    reference = _STEP_OUTPUT.match(_deploy_env_vars()[_NUMBER_VAR])
    assert reference is not None
    assert _step_index(reference["id"]) < _step_index("deploy")
    assert "if" not in step
    # Inputs arrive through `env`, never templated into the script text.
    assert "${{" not in step["run"]

    process, written = _run_step(step, {provider_env: _PROVIDER}, tmp_path)

    assert process.returncode == 0, process.stderr
    assert written == {output: _NUMBER}


@pytest.mark.parametrize(
    "provider",
    [
        "",  # an unset `vars.` reference renders as the empty string
        _PROJECT,
        _PROVIDER.replace(_NUMBER, _PROJECT),  # a project id where the number belongs
        _PROVIDER.replace(_NUMBER, f"{_NUMBER}x"),
        _PROVIDER.rsplit("/providers/", 1)[0],  # the pool, not the provider
        f"{_PROVIDER}\nprojects/1/x",
    ],
)
def test_deploy_stops_on_a_provider_without_a_project_number(tmp_path: Path, provider: str) -> None:
    """No guessed or empty number reaches the service: the job fails before the rollout."""
    step, provider_env, _ = _project_number_step()

    process, written = _run_step(step, {provider_env: provider}, tmp_path)

    assert process.returncode != 0
    assert written == {}
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in process.stdout + process.stderr


_PRIVATE_AND_OURS = {
    "projectNumber": _NUMBER,
    "iamConfiguration": {
        "publicAccessPrevention": "enforced",
        "uniformBucketLevelAccess": {"enabled": True},
    },
}


def _with(**changes: Any) -> dict[str, Any]:
    """:data:`_PRIVATE_AND_OURS` with top-level or ``iamConfiguration`` fields replaced."""
    resource: dict[str, Any] = json.loads(json.dumps(_PRIVATE_AND_OURS))
    for key, value in changes.items():
        target = resource if key == "projectNumber" else resource["iamConfiguration"]
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    return resource


def _evidence_check_step() -> tuple[int, dict[str, Any], str, str]:
    """The deploy job's evidence bucket check: ``(index, step, bucket env, number env)``.

    Found by its inputs: the exact bucket expression the service is given and the
    exact project number the service is given, so the check cannot judge another bucket
    or another number than the backend will use.
    """
    env_vars = _deploy_env_vars()
    found = [
        (index, step)
        for index, step in enumerate(_deploy_steps())
        if env_vars[_EVIDENCE_VAR] in step.get("env", {}).values()
        and env_vars[_NUMBER_VAR] in step.get("env", {}).values()
    ]
    assert len(found) == 1, "no single deploy-backend step checks the evidence bucket"
    index, step = found[0]
    env = step["env"]
    bucket_env = next(k for k, v in env.items() if v == env_vars[_EVIDENCE_VAR])
    number_env = next(k for k, v in env.items() if v == env_vars[_NUMBER_VAR])
    return index, step, bucket_env, number_env


def _fake_gcloud_and_curl(tmp_path: Path) -> Path:
    """A ``bin`` directory whose ``gcloud`` mints a token and whose ``curl`` answers buckets.get.

    ``curl`` appends its arguments to ``$FAKE_CURL_ARGS``; it fails like ``curl --fail``
    on a 403 when ``$FAKE_CURL_FAIL`` is set, and otherwise prints ``$FAKE_BUCKET_JSON``.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gcloud").write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "auth print-access-token" ]; then echo fake-token; exit 0; fi\n'
        'echo "unexpected: gcloud $*" >&2; exit 2\n',
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" >> "$FAKE_CURL_ARGS"\n'
        'if [ -n "$FAKE_CURL_FAIL" ]; then\n'
        '  echo "curl: (22) The requested URL returned error: 403" >&2; exit 22\n'
        "fi\n"
        'printf "%s" "$FAKE_BUCKET_JSON"\n',
        encoding="utf-8",
    )
    for tool in ("gcloud", "curl"):
        (bin_dir / tool).chmod(0o755)
    return bin_dir


@pytest.mark.parametrize(
    ("resource", "curl_fails", "passes", "said"),
    [
        (_PRIVATE_AND_OURS, False, True, ""),
        (_with(projectNumber="987654321098"), False, False, "987654321098"),
        (_with(projectNumber=None), False, False, _NUMBER),
        (_with(publicAccessPrevention="inherited"), False, False, "inherited"),
        (_with(publicAccessPrevention=None), False, False, "public access prevention"),
        (_with(uniformBucketLevelAccess={"enabled": False}), False, False, "uniform"),
        (_PRIVATE_AND_OURS, True, False, "gcp-bootstrap.sh"),
    ],
    ids=[
        "private-and-ours",
        "foreign-owner",
        "no-owner",
        "prevention-inherited",
        "prevention-absent",
        "not-uniform",
        "unreadable",
    ],
)
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deploy_checks_the_evidence_bucket_is_private_and_ours(
    tmp_path: Path,
    environment: str,
    resource: dict[str, Any],
    curl_fails: bool,
    passes: bool,
    said: str,
) -> None:
    """Finding 5: a deploy whose bootstrap was never re-run must not go green.

    The check sits with the uploads-bucket health check, after the rollout, and judges
    the privacy-and-owner result the backend's own first-use check judges, not mere
    existence: public access prevention enforced, uniform access on, and the owning
    project number equal to the one the service was given.
    """
    index, step, bucket_env, number_env = _evidence_check_step()
    assert index > _step_index("deploy")
    assert "if" not in step
    assert not step.get("continue-on-error", False)
    assert "${{" not in step["run"]
    bucket = _render(_deploy_env_vars()[_EVIDENCE_VAR], environment, {})
    curl_args = tmp_path / "curl_args"
    env = {
        "PATH": f"{_fake_gcloud_and_curl(tmp_path)}{os.pathsep}{os.environ['PATH']}",
        bucket_env: bucket,
        number_env: _NUMBER,
        "FAKE_BUCKET_JSON": json.dumps(resource),
        "FAKE_CURL_ARGS": str(curl_args),
    }
    if curl_fails:
        env["FAKE_CURL_FAIL"] = "1"

    process, _ = _run_step(step, env, tmp_path)

    said_by_step = process.stdout + process.stderr
    assert (process.returncode == 0) is passes, said_by_step
    assert said in said_by_step
    if not passes:
        assert bucket in said_by_step
    # The JSON API's buckets.get for exactly this bucket, as the deployer account.
    args = curl_args.read_text(encoding="utf-8").splitlines()
    assert any(a.startswith(f"https://storage.googleapis.com/storage/v1/b/{bucket}") for a in args)
    assert "Authorization: Bearer fake-token" in args
