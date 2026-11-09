"""``scripts/scheduler_reconcile.py``: the Cloud Scheduler reconcile plan, apply and wiring.

No gcloud: actual state is plain dicts and commands go through a recording runner. The tests that
matter most are the ones that keep an unmanaged job alive; the ownership filter is the only
thing standing between a deploy and a stranger's job, so each is written to go red without it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "scheduler_reconcile", ROOT / "scripts" / "scheduler_reconcile.py"
)
assert _spec is not None
assert _spec.loader is not None
rc = importlib.util.module_from_spec(_spec)
sys.modules["scheduler_reconcile"] = rc
_spec.loader.exec_module(rc)

HOST = "https://staging.lemelyig.com"
SECRETS = {"WAITLIST_DIGEST_SECRET": "digest-secret-value", "OTHER_SECRET": "other-secret-value"}


def desired(*ids: str, secret: str = "WAITLIST_DIGEST_SECRET") -> list[object]:
    return [
        rc.DesiredJob(
            id=i,
            schedule="0 7 * * *",
            time_zone="UTC",
            method="POST",
            path=f"/api/internal/{i}",
            secret=secret,
            description=f"job {i}",
        )
        for i in ids
    ]


def managed(env: str, job_id: str) -> dict[str, object]:
    return {
        "name": f"projects/p/locations/us-central1/jobs/lemely-{env}-{job_id}",
        "description": f"{rc.MARKER}; id={job_id}; whatever",
    }


def unmanaged(name: str, description: str = "made by hand") -> dict[str, object]:
    return {"name": f"projects/p/locations/us-central1/jobs/{name}", "description": description}


def make_plan(
    want: list[object], have: list[dict[str, object]], secrets: Mapping[str, str] = SECRETS
):
    return rc.plan(want, have, environment="staging", host=HOST, secrets=secrets)


def names(items: Sequence[object]) -> list[str]:
    return [getattr(i, "name", i) for i in items]  # type: ignore[misc]


# -- plan -------------------------------------------------------------------


def test_a_new_job_is_created_with_its_public_uri_and_the_marker() -> None:
    p = make_plan(desired("waitlist-digest"), [])

    assert names(p.create) == ["lemely-staging-waitlist-digest"]
    assert p.update == [] and p.delete == [] and p.skipped == [] and p.conflicts == []
    job = p.create[0]
    assert job.uri == "https://staging.lemelyig.com/api/internal/waitlist-digest"
    assert rc.MARKER in job.description
    assert SECRETS["WAITLIST_DIGEST_SECRET"] not in repr(job)  # the value never shows in a repr


def test_an_existing_managed_job_is_always_updated_so_a_rotated_secret_propagates() -> None:
    p = make_plan(desired("waitlist-digest"), [managed("staging", "waitlist-digest")])

    assert names(p.update) == ["lemely-staging-waitlist-digest"]
    assert p.create == [] and p.delete == []


def test_a_rename_creates_the_new_job_and_deletes_the_old_managed_one() -> None:
    p = make_plan(desired("digest-v2"), [managed("staging", "waitlist-digest")])

    assert names(p.create) == ["lemely-staging-digest-v2"]
    assert p.delete == ["lemely-staging-waitlist-digest"]


def test_a_job_removed_from_the_file_is_deleted() -> None:
    have = [managed("staging", "waitlist-digest"), managed("staging", "old-thing")]
    p = make_plan(desired("waitlist-digest"), have)

    assert p.delete == ["lemely-staging-old-thing"]
    assert names(p.update) == ["lemely-staging-waitlist-digest"]


def test_an_empty_secret_skips_the_job_and_never_deletes_or_touches_it() -> None:
    have = [managed("staging", "waitlist-digest")]
    for secrets in ({}, {"WAITLIST_DIGEST_SECRET": ""}, {"WAITLIST_DIGEST_SECRET": "   "}):
        p = make_plan(desired("waitlist-digest"), have, secrets)
        assert p.skipped == ["lemely-staging-waitlist-digest"]
        assert p.create == [] and p.update == [] and p.delete == []
    # Skipped and not yet existing: still just skipped.
    assert make_plan(desired("waitlist-digest"), [], {}).skipped == [
        "lemely-staging-waitlist-digest"
    ]


def test_an_empty_secret_on_one_job_does_not_stop_the_others() -> None:
    want = [*desired("a"), *desired("b", secret="OTHER_SECRET")]
    p = make_plan(want, [], {"OTHER_SECRET": "x"})
    assert names(p.create) == ["lemely-staging-b"]
    assert p.skipped == ["lemely-staging-a"]


@pytest.mark.parametrize(
    "survivor",
    [
        unmanaged("lemely-staging-handmade"),  # right prefix, no marker
        unmanaged("lemely-staging-handmade", description=""),
        {"name": "projects/p/locations/us-central1/jobs/lemely-staging-nodesc"},  # no description
        unmanaged("nightly-backup"),  # someone else's job
        unmanaged("nightly-backup", description=f"{rc.MARKER}; copied the marker"),  # wrong prefix
        managed("production", "waitlist-digest"),  # the other environment's job
        managed("production", "stray"),
    ],
    ids=[
        "no-marker",
        "empty-description",
        "no-description",
        "other-job",
        "marker-wrong-prefix",
        "other-env",
        "other-env-stray",
    ],
)
def test_jobs_this_deploy_does_not_own_are_never_deleted(survivor: dict[str, object]) -> None:
    p = make_plan(desired("waitlist-digest"), [survivor, managed("staging", "waitlist-digest")])

    assert p.delete == []
    assert str(survivor["name"]).rsplit("/", 1)[-1] not in names(p.update + p.create)


def test_an_unmanaged_job_with_a_desired_name_is_a_conflict_not_an_overwrite() -> None:
    p = make_plan(desired("waitlist-digest"), [unmanaged("lemely-staging-waitlist-digest")])

    assert p.conflicts == ["lemely-staging-waitlist-digest"]
    assert p.create == [] and p.update == [] and p.delete == []


def test_a_secret_that_would_break_gcloud_header_syntax_fails_loudly() -> None:
    for bad in ("a,b", "has space", 'quo"te'):
        with pytest.raises(rc.ReconcileError):
            make_plan(desired("x"), [], {"WAITLIST_DIGEST_SECRET": bad})


def test_unknown_environment_is_refused() -> None:
    with pytest.raises(rc.ReconcileError):
        rc.plan([], [], environment="prod", host=HOST, secrets={})


# -- apply ------------------------------------------------------------------


class Runner:
    def __init__(self, fail_on: str | None = None, leak: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on
        self.leak = leak

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        if self.fail_on and self.fail_on in " ".join(command):
            return subprocess.CompletedProcess(command, 1, "", f"boom {self.leak or ''}")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_apply_runs_creates_then_updates_then_deletes_with_the_right_flags() -> None:
    p = make_plan(
        desired("new", "kept"),
        [
            managed("staging", "kept"),
            managed("staging", "gone"),
            unmanaged("lemely-staging-handmade"),
        ],
    )
    run = Runner()
    logged: list[str] = []

    rc.apply(p, project="proj", location="us-central1", run=run, log=logged.append)

    verbs = [c[3] + " " + (c[4] if c[3] == "delete" else c[5]) for c in run.commands]
    assert verbs == [
        "create lemely-staging-new",
        "update lemely-staging-kept",
        "delete lemely-staging-gone",
    ]
    create, update, delete = run.commands
    assert "--headers=X-Cron-Secret=digest-secret-value" in create
    assert "--update-headers=X-Cron-Secret=digest-secret-value" in update  # rotation propagates
    assert "--uri=https://staging.lemelyig.com/api/internal/new" in create
    assert "--schedule=0 7 * * *" in create and "--time-zone=UTC" in create
    assert delete[:4] == ["gcloud", "scheduler", "jobs", "delete"]
    assert all("handmade" not in " ".join(c) for c in run.commands)
    assert all("digest-secret-value" not in line for line in logged)


def test_apply_warns_for_a_skipped_job_and_issues_no_command_for_it() -> None:
    p = make_plan(desired("waitlist-digest"), [managed("staging", "waitlist-digest")], {})
    run = Runner()
    logged: list[str] = []

    rc.apply(p, project="proj", location="us-central1", run=run, log=logged.append)

    assert run.commands == []
    assert any(
        line.startswith("::warning::") and "lemely-staging-waitlist-digest" in line
        for line in logged
    )


def test_any_gcloud_failure_raises_and_the_secret_is_redacted() -> None:
    p = make_plan(desired("a"), [])
    run = Runner(fail_on="create", leak="digest-secret-value")

    with pytest.raises(rc.ReconcileError) as caught:
        rc.apply(p, project="proj", location="us-central1", run=run, log=lambda _m: None)

    assert "digest-secret-value" not in str(caught.value)
    assert "boom ***" in str(caught.value)


def test_a_failed_create_stops_before_any_delete() -> None:
    p = make_plan(desired("new"), [managed("staging", "gone")])
    run = Runner(fail_on="create")
    with pytest.raises(rc.ReconcileError):
        rc.apply(p, project="proj", location="us-central1", run=run, log=lambda _m: None)
    assert all(c[3] != "delete" for c in run.commands)


def test_create_and_update_both_carry_the_retry_policy() -> None:
    p = make_plan(desired("new", "kept"), [managed("staging", "kept")])
    run = Runner()
    rc.apply(p, project="proj", location="us-central1", run=run, log=lambda _m: None)

    create, update = run.commands
    assert (create[3], update[3]) == ("create", "update")
    for command in (create, update):
        assert "--max-retry-attempts=3" in command
        assert "--min-backoff=6m" in command  # the first retry lands after the 5-minute lease
        assert "--max-backoff=30m" in command


def test_the_first_retry_waits_longer_than_the_digest_claim_lease() -> None:
    from lemely.db.waitlist_repo import PENDING_CLAIM_LEASE

    minutes = int(next(f for f in rc.RETRY_FLAGS if "min-backoff" in f).split("=")[1].rstrip("m"))
    assert minutes * 60 > PENDING_CLAIM_LEASE.total_seconds()


# -- main -------------------------------------------------------------------


def _jobs_file(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "waitlist-digest",
                        "schedule": "0 7 * * *",
                        "path": "/api/x",
                        "secret": "WAITLIST_DIGEST_SECRET",
                    }
                ]
            }
        )
    )
    return path


def _list_runner(actual: list[dict[str, object]], fail_list: bool = False) -> Runner:
    class ListingRunner(Runner):
        def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[3] == "list":
                self.commands.append(list(command))
                if fail_list:
                    return subprocess.CompletedProcess(command, 1, "", "denied")
                return subprocess.CompletedProcess(command, 0, json.dumps(actual), "")
            return super().__call__(command)

    return ListingRunner()


ARGS = ["--environment", "staging", "--host", HOST, "--project", "proj"]


def test_main_reconciles_and_reads_secrets_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAITLIST_DIGEST_SECRET", "from-env-secret")
    run = _list_runner([managed("staging", "stale")])

    code = rc.main([*ARGS, "--jobs-file", str(_jobs_file(tmp_path))], run=run)

    assert code == 0
    assert [c[3] for c in run.commands] == ["list", "create", "delete"]
    assert any("--headers=X-Cron-Secret=from-env-secret" in c for c in run.commands[1])


def test_main_dry_run_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAITLIST_DIGEST_SECRET", "s")
    run = _list_runner([managed("staging", "stale")])
    assert rc.main([*ARGS, "--dry-run", "--jobs-file", str(_jobs_file(tmp_path))], run=run) == 0
    assert [c[3] for c in run.commands] == ["list"]


def test_main_fails_on_a_conflict_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WAITLIST_DIGEST_SECRET", "s")
    run = _list_runner([unmanaged("lemely-staging-waitlist-digest"), managed("staging", "stale")])

    assert rc.main([*ARGS, "--jobs-file", str(_jobs_file(tmp_path))], run=run) == 1

    assert [c[3] for c in run.commands] == ["list"]  # not even the stale managed job was deleted
    assert "::error::" in capsys.readouterr().out


def test_main_fails_when_listing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAITLIST_DIGEST_SECRET", "s")
    run = _list_runner([], fail_list=True)
    assert rc.main([*ARGS, "--jobs-file", str(_jobs_file(tmp_path))], run=run) == 1


def test_main_with_no_secret_warns_and_succeeds_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("WAITLIST_DIGEST_SECRET", raising=False)
    run = _list_runner([managed("staging", "waitlist-digest")])

    assert rc.main([*ARGS, "--jobs-file", str(_jobs_file(tmp_path))], run=run) == 0

    assert [c[3] for c in run.commands] == ["list"]
    assert "::warning::" in capsys.readouterr().out


# -- the committed desired state and the workflow wiring --------------------

DEPLOY = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")


def test_the_committed_job_file_is_valid_and_starts_with_the_waitlist_digest() -> None:
    jobs = rc.load_desired(ROOT / ".github/scheduler-jobs.json")

    first = jobs[0]
    assert (first.id, first.schedule, first.time_zone, first.method) == (
        "waitlist-digest",
        "0 7 * * *",
        "UTC",
        "POST",
    )
    assert first.path == "/api/internal/waitlist/digest"
    assert first.secret == "WAITLIST_DIGEST_SECRET"
    assert len({j.id for j in jobs}) == len(jobs)


def test_every_job_secret_is_mapped_into_the_reconcile_step_of_deploy_yml() -> None:
    start = DEPLOY.index("python3 scripts/scheduler_reconcile.py")
    step = DEPLOY[DEPLOY.rindex("      - name:", 0, start) : start]
    for job in rc.load_desired(ROOT / ".github/scheduler-jobs.json"):
        assert f"{job.secret}: ${{{{ secrets.{job.secret} }}}}" in step, job.secret


def test_the_reconcile_step_targets_the_public_host_and_runs_after_the_serving_check() -> None:
    assert DEPLOY.index("Verify the serving revision runs this commit") < DEPLOY.index(
        "python3 scripts/scheduler_reconcile.py"
    )
    start = DEPLOY.index("python3 scripts/scheduler_reconcile.py")
    step = DEPLOY[start : start + 600]
    assert "lemelyig.com" in step and "staging.lemelyig.com" in step
    assert "--environment" in step and "resolve-env.outputs.environment" in step


def test_validation_rejects_bad_job_files(tmp_path: Path) -> None:
    def load(job: dict[str, object]) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"jobs": [job]}))
        rc.load_desired(path)

    base = {"id": "ok", "schedule": "* * * * *", "path": "/x", "secret": "SOME_SECRET"}
    load(base)
    for patch in ({"id": "Bad_Id"}, {"path": "no-slash"}, {"secret": "lower"}, {"method": "FETCH"}):
        with pytest.raises(rc.ReconcileError):
            load({**base, **patch})
    path = tmp_path / "dup.json"
    path.write_text(json.dumps({"jobs": [base, base]}))
    with pytest.raises(rc.ReconcileError):
        rc.load_desired(path)
