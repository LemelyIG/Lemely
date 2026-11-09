#!/usr/bin/env python
"""Reconcile Cloud Scheduler with ``.github/scheduler-jobs.json`` (run by deploy.yml).

Desired state is the committed file; actual state is what ``gcloud scheduler jobs list`` returns.
For one environment the job names are ``lemely-<environment>-<id>``. The plan is:

* **create** a desired job that does not exist;
* **update** one that does (schedule, URI and headers are always rewritten, so a rotated secret
  reaches Cloud Scheduler on the next deploy);
* **delete** a job that is *managed* but no longer desired, which is how a rename or a removal
  from the file takes effect.

**Ownership.** A job is managed only when its name starts with ``lemely-<environment>-`` AND its
description carries :data:`MARKER`. Cloud Scheduler jobs have no labels (gcloud 588 has no
``--labels`` for them, and the API's Job resource has no such field), so the marker lives in the
description. Deletion never touches anything else in the project, including a hand-made
``lemely-<environment>-...`` job without the marker. If a desired name is already taken by an
unmanaged job the run fails instead of overwriting it.

**Secrets.** Each job names a secret; its value is read from the environment variable of the same
name. An empty or missing value skips that job with a ``::warning::`` and leaves any existing job
alone (a missing secret must not destroy a job). A value that could break gcloud's
``KEY=VALUE,...`` header syntax fails the run. Secret values are never printed.

The plan is pure (:func:`plan`) so it is tested without gcloud; :func:`apply` runs it through an
injectable command runner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

MARKER: Final = "managed-by=lemely-deploy"
ENVIRONMENTS: Final = ("staging", "production")
#: Retries Cloud Scheduler makes after a failed attempt (any non-2xx, including the digest's 503
#: ``digest_pending``). 6 minutes is the minimum backoff on purpose: the backend lets a retry take
#: over an unconfirmed claim only after 5 minutes, so the first retry lands after that lease.
RETRY_FLAGS: Final = (
    "--max-retry-attempts=3",
    "--min-backoff=6m",
    "--max-backoff=30m",
)
SECRET_HEADER: Final = "X-Cron-Secret"  # noqa: S105 - a header name
_ID_RE: Final = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_ENV_NAME_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SECRET_VALUE_RE: Final = re.compile(r"^[A-Za-z0-9_.~+/:=@-]+$")
_METHODS: Final = ("GET", "POST", "PUT", "DELETE", "PATCH")

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class ReconcileError(Exception):
    """The desired file is invalid, a job is blocked, or a gcloud call failed."""


@dataclass(frozen=True, slots=True)
class DesiredJob:
    """One entry of ``scheduler-jobs.json``."""

    id: str
    schedule: str
    time_zone: str
    method: str
    path: str
    secret: str
    description: str


@dataclass(frozen=True, slots=True)
class PlannedJob:
    """A desired job resolved for one environment, with its secret value."""

    name: str
    job: DesiredJob
    uri: str
    secret_value: str = field(repr=False)

    @property
    def description(self) -> str:
        return f"{MARKER}; id={self.job.id}; {self.job.description}".strip().rstrip(";")


@dataclass(frozen=True, slots=True)
class Plan:
    """What to do. ``skipped`` jobs are left exactly as they are."""

    create: list[PlannedJob] = field(default_factory=list)
    update: list[PlannedJob] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def load_desired(path: Path) -> list[DesiredJob]:
    """Parse and validate the desired-state file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs: list[DesiredJob] = []
    seen: set[str] = set()
    for raw in data["jobs"]:
        job_id = str(raw["id"])
        if not _ID_RE.match(job_id):
            raise ReconcileError(f"job id {job_id!r} must match {_ID_RE.pattern}")
        if job_id in seen:
            raise ReconcileError(f"duplicate job id {job_id!r}")
        seen.add(job_id)
        method = str(raw.get("method", "POST")).upper()
        if method not in _METHODS:
            raise ReconcileError(f"job {job_id!r}: unsupported method {method!r}")
        path_ = str(raw["path"])
        if not path_.startswith("/"):
            raise ReconcileError(f"job {job_id!r}: path must start with '/'")
        secret = str(raw["secret"])
        if not _ENV_NAME_RE.match(secret):
            raise ReconcileError(f"job {job_id!r}: secret name {secret!r} is not an env-var name")
        jobs.append(
            DesiredJob(
                id=job_id,
                schedule=str(raw["schedule"]),
                time_zone=str(raw.get("timeZone", "UTC")),
                method=method,
                path=path_,
                secret=secret,
                description=str(raw.get("description", "")),
            )
        )
    return jobs


def job_name(environment: str, job_id: str) -> str:
    """The Cloud Scheduler job id for ``job_id`` in ``environment``."""
    return f"lemely-{environment}-{job_id}"


def _short(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def is_managed(actual: Mapping[str, object], environment: str) -> bool:
    """``True`` only for a job this deploy owns: right name prefix AND the marker."""
    name = _short(str(actual.get("name", "")))
    description = str(actual.get("description") or "")
    return name.startswith(f"lemely-{environment}-") and MARKER in description


def plan(
    desired: Sequence[DesiredJob],
    actual: Sequence[Mapping[str, object]],
    *,
    environment: str,
    host: str,
    secrets: Mapping[str, str],
) -> Plan:
    """Compare desired with actual for one environment. Pure: no gcloud, no I/O."""
    if environment not in ENVIRONMENTS:
        raise ReconcileError(f"unknown environment {environment!r}")
    by_name = {_short(str(a.get("name", ""))): a for a in actual}
    desired_names = {job_name(environment, job.id) for job in desired}
    create: list[PlannedJob] = []
    update: list[PlannedJob] = []
    skipped: list[str] = []
    conflicts: list[str] = []
    for job in desired:
        name = job_name(environment, job.id)
        value = secrets.get(job.secret, "").strip()
        existing = by_name.get(name)
        if existing is not None and not is_managed(existing, environment):
            conflicts.append(name)
            continue
        if not value:
            skipped.append(name)
            continue
        if not _SECRET_VALUE_RE.match(value):
            raise ReconcileError(
                f"the secret {job.secret} has characters that break gcloud's header syntax; "
                "use letters, digits and _ . ~ + / : = @ -"
            )
        planned = PlannedJob(name, job, host.rstrip("/") + job.path, value)
        (update if existing is not None else create).append(planned)
    delete = sorted(
        _short(str(a["name"]))
        for a in actual
        if is_managed(a, environment) and _short(str(a["name"])) not in desired_names
    )
    return Plan(create, update, delete, skipped, conflicts)


def _when(planned: PlannedJob) -> str:
    return f"{planned.job.schedule} {planned.job.time_zone}"


def _command(verb: str, planned: PlannedJob, project: str, location: str) -> list[str]:
    job = planned.job
    header_flag = "--headers" if verb == "create" else "--update-headers"
    return [
        "gcloud",
        "scheduler",
        "jobs",
        verb,
        "http",
        planned.name,
        f"--project={project}",
        f"--location={location}",
        f"--schedule={job.schedule}",
        f"--time-zone={job.time_zone}",
        f"--uri={planned.uri}",
        f"--http-method={job.method}",
        f"--description={planned.description}",
        f"{header_flag}={SECRET_HEADER}={planned.secret_value}",
        *RETRY_FLAGS,
        "--quiet",
    ]


def apply(
    the_plan: Plan, *, project: str, location: str, run: Runner, log: Callable[[str], None] = print
) -> None:
    """Execute ``the_plan`` (creates, updates, then deletes); any failing command raises."""
    secrets = [p.secret_value for p in (*the_plan.create, *the_plan.update)]

    def execute(command: Sequence[str]) -> None:
        result = run(command)
        if result.returncode != 0:
            detail = f"{result.stdout or ''}\n{result.stderr or ''}"
            for secret in secrets:
                detail = detail.replace(secret, "***")
            raise ReconcileError(f"{' '.join(command[:6])} failed:\n{detail.strip()}")

    for name in the_plan.skipped:
        log(f"::warning::Skipping {name}: its secret is empty, so the job is left as it is.")
    for planned in the_plan.create:
        log(f"create {planned.name} ({_when(planned)}) -> {planned.uri}")
        execute(_command("create", planned, project, location))
    for planned in the_plan.update:
        log(f"update {planned.name} ({_when(planned)}) -> {planned.uri}")
        execute(_command("update", planned, project, location))
    for name in the_plan.delete:
        log(f"delete {name} (managed, no longer in scheduler-jobs.json)")
        execute(
            [
                "gcloud", "scheduler", "jobs", "delete", name,
                f"--project={project}", f"--location={location}", "--quiet",
            ]
        )  # fmt: skip


def _gcloud(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def list_actual(project: str, location: str, run: Runner) -> list[dict[str, object]]:
    """Every job in the location, as ``gcloud scheduler jobs list`` reports it."""
    result = run(
        [
            "gcloud", "scheduler", "jobs", "list",
            f"--project={project}", f"--location={location}", "--format=json",
        ]
    )  # fmt: skip
    if result.returncode != 0:
        raise ReconcileError(f"listing scheduler jobs failed:\n{result.stderr.strip()}")
    parsed = json.loads(result.stdout or "[]")
    return [dict(item) for item in parsed]


def main(argv: Sequence[str] | None = None, run: Runner = _gcloud) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--host", required=True, help="public origin, e.g. https://lemelyig.com")
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--jobs-file", type=Path, default=Path(".github/scheduler-jobs.json"))
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args(argv)
    try:
        desired = load_desired(args.jobs_file)
        the_plan = plan(
            desired,
            list_actual(args.project, args.location, run),
            environment=args.environment,
            host=args.host,
            secrets=os.environ,
        )
        if the_plan.conflicts:
            raise ReconcileError(
                "these jobs exist without the lemely-deploy ownership marker, so they will not "
                f"be overwritten: {', '.join(the_plan.conflicts)}. Delete or rename them."
            )
        if args.dry_run:
            created = [p.name for p in the_plan.create]
            updated = [p.name for p in the_plan.update]
            print(
                f"create={created} update={updated} "
                f"delete={the_plan.delete} skipped={the_plan.skipped}"
            )
            return 0
        apply(the_plan, project=args.project, location=args.location, run=run)
    except (ReconcileError, KeyError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
