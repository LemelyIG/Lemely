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
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from lemely.runtime.config import StorageSettings

_ROOT = Path(__file__).resolve().parent.parent
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_BOOTSTRAP = _ROOT / "scripts" / "gcp-bootstrap.sh"
_PROJECT = "proj-1234"
_EVIDENCE_VAR = "LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET"
_OTHER_BUCKET_VARS = ("LEMELY_STORAGE__BUCKET", "LEMELY_STORAGE__AVATAR_BUCKET")

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


def _deploy_env_vars() -> dict[str, str]:
    """The ``env_vars`` block of the Cloud Run deploy step, as name -> expression."""
    workflow = yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    deploy = next(step for step in steps if step.get("id") == "deploy")
    pairs = (line.split("=", 1) for line in deploy["with"]["env_vars"].splitlines() if line)
    return {name: value for name, value in pairs}


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
    evidence_grants = [
        command.split()
        for command in _commands(body, "add-iam-policy-binding")
        if '"gs://$EVIDENCE_BUCKET"' in command.split()
    ]
    assert len(evidence_grants) == 1
    assert '--member="serviceAccount:${RUNTIME_SA}"' in evidence_grants[0]
    assert '--role="roles/storage.legacyBucketReader"' in evidence_grants[0]

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
