"""``scripts/scheduler_reconcile.py``: the Cloud Scheduler reconcile plan, apply and wiring.

No gcloud: actual state is plain dicts and commands go through a recording runner. The tests that
matter most are the ones that keep an unmanaged job alive; the ownership filter is the only
thing standing between a deploy and a stranger's job, so each is written to go red without it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

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


@pytest.mark.parametrize("bad", ["ok\n", "Bad", "x" * 42, "", "-lead", "a b", "a;b", "a/b"])
def test_the_plan_refuses_a_job_id_that_would_make_a_bad_scheduler_name(bad: str) -> None:
    # The plan is the last stop before the name reaches gcloud, and a job can be built without
    # going through the file loader, so the plan checks the id and the name again.
    with pytest.raises(rc.ReconcileError):
        make_plan(desired(bad), [])


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


def _update_command(job: object) -> list[str]:
    run = Runner()
    p = make_plan([job], [managed("staging", job.id)])  # type: ignore[attr-defined]
    rc.apply(p, project="proj", location="us-central1", run=run, log=lambda _m: None)
    (command,) = run.commands
    assert command[3] == "update"
    return command


def test_an_update_puts_back_the_default_deadline_once_the_file_drops_it() -> None:
    # gcloud has no flag that clears an attempt deadline, so a job whose attemptDeadline was
    # removed from the file is sent Scheduler's own default; otherwise the old one would stay.
    (job,) = desired("x")
    assert job.attempt_deadline is None  # type: ignore[attr-defined]

    assert "--attempt-deadline=180s" in _update_command(job)
    create = make_plan([job], [])
    run = Runner()
    rc.apply(create, project="proj", location="us-central1", run=run, log=lambda _m: None)
    assert not [f for f in run.commands[0] if f.startswith("--attempt-deadline")]


def test_an_update_to_no_retries_clears_the_backoff_the_job_had() -> None:
    (job,) = desired("x")
    no_retries = dataclasses.replace(job, max_retry_attempts=0)  # type: ignore[type-var]

    command = _update_command(no_retries)

    assert "--max-retry-attempts=0" in command
    assert "--clear-min-backoff" in command and "--clear-max-backoff" in command
    assert not [f for f in command if f.startswith(("--min-backoff", "--max-backoff"))]


@pytest.mark.parametrize("retries", [0, 3])
def test_a_managed_update_clears_any_retry_duration_set_by_hand(retries: int) -> None:
    # The file has no maxRetryDuration, so a value left on the job (set by hand or by an older
    # deploy) would silently cap the retries the file asks for. Every update clears it.
    (job,) = desired("x")
    with_retries = dataclasses.replace(job, max_retry_attempts=retries)  # type: ignore[type-var]

    assert "--clear-max-retry-duration" in _update_command(with_retries)
    run = Runner()
    rc.apply(make_plan([job], []), project="proj", location="us-central1", run=run, log=print)
    assert not [f for f in run.commands[0] if f.startswith("--clear-")]


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
# The reconcile invocation (line-continued arguments), not the preflight step's `--preflight`.
RECONCILE_CALL = "python3 scripts/scheduler_reconcile.py \\\n"


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


def test_the_committed_job_file_schedules_the_billing_sweep_every_minute() -> None:
    # Cloud Run runs at --min-instances=0, so the in-process sweep loop (60 s poll) sleeps
    # while idle; this job is what runs it. One minute is Scheduler's floor and the loop's
    # own interval. See docs/deployment.md.
    sweep = {j.id: j for j in rc.load_desired(ROOT / ".github/scheduler-jobs.json")}["sweep"]

    assert (sweep.schedule, sweep.time_zone, sweep.method) == ("* * * * *", "UTC", "POST")
    assert sweep.path == "/api/internal/jobs/sweep"
    assert sweep.secret == "SWEEP_JOBS_SECRET"


def test_the_sweep_secret_reaches_the_service_as_the_jobs_secret_setting() -> None:
    # The route reads settings.notifications.jobs_secret (LEMELY_NOTIFICATIONS__JOBS_SECRET).
    line = "LEMELY_NOTIFICATIONS__JOBS_SECRET=${{ secrets.SWEEP_JOBS_SECRET }}"
    assert line in DEPLOY
    # Environment-level, in the same env_vars block as the digest secret it mirrors.
    digest = "LEMELY_WAITLIST__DIGEST_SECRET=${{ secrets.WAITLIST_DIGEST_SECRET }}"
    assert abs(DEPLOY.index(line) - DEPLOY.index(digest)) < 400


def test_every_job_secret_is_mapped_into_the_reconcile_step_of_deploy_yml() -> None:
    start = DEPLOY.index(RECONCILE_CALL)
    step = DEPLOY[DEPLOY.rindex("      - name:", 0, start) : start]
    for job in rc.load_desired(ROOT / ".github/scheduler-jobs.json"):
        assert f"{job.secret}: ${{{{ secrets.{job.secret} }}}}" in step, job.secret


def test_the_reconcile_step_targets_the_public_host_and_runs_after_the_serving_check() -> None:
    assert DEPLOY.index("Verify the serving revision runs this commit") < DEPLOY.index(
        RECONCILE_CALL
    )
    start = DEPLOY.index(RECONCILE_CALL)
    step = DEPLOY[start : start + 600]
    assert "lemelyig.com" in step and "staging.lemelyig.com" in step
    assert "--environment" in step and "resolve-env.outputs.environment" in step


def test_validation_rejects_bad_job_files(tmp_path: Path) -> None:
    def load(job: dict[str, object]) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"jobs": [job]}))
        rc.load_desired(path)

    base: dict[str, object] = {
        "id": "ok",
        "schedule": "* * * * *",
        "path": "/x",
        "secret": "SOME_SECRET",
    }
    load(base)
    patches: list[dict[str, object]] = [
        {"id": "Bad_Id"},
        {"path": "no-slash"},
        {"secret": "lower"},
        {"method": "FETCH"},
        # A trailing newline passes a ``$``-anchored ``match``; every check must be a full match.
        {"id": "ok\n"},
        {"secret": "SOME_SECRET\n"},
        {"attemptDeadline": "90s\n"},
        {"id": "x" * 42},
    ]
    for patch in patches:
        with pytest.raises(rc.ReconcileError):
            load({**base, **patch})
    path = tmp_path / "dup.json"
    path.write_text(json.dumps({"jobs": [base, base]}))
    with pytest.raises(rc.ReconcileError):
        rc.load_desired(path)


# -- per-job delivery policy and required secrets (review round 2) ------------

COMMITTED = ROOT / ".github/scheduler-jobs.json"
SWEEP_SECRET = "sweep-secret-" + "x" * 40
BOTH = {"WAITLIST_DIGEST_SECRET": "digest-secret-value", "SWEEP_JOBS_SECRET": SWEEP_SECRET}


def _committed_commands(*, existing: bool) -> dict[str, list[str]]:
    jobs = rc.load_desired(COMMITTED)
    have = [managed("staging", j.id) for j in jobs] if existing else []
    run = Runner()
    rc.apply(
        make_plan(jobs, have, BOTH),  # type: ignore[arg-type]
        project="proj",
        location="us-central1",
        run=run,
        log=lambda _m: None,
    )
    return {c[5]: c for c in run.commands}


@pytest.mark.parametrize("existing", [False, True], ids=["create", "update"])
def test_the_sweep_job_gets_no_retries_and_an_explicit_attempt_deadline(existing: bool) -> None:
    # A retry of a pass that overran would land while the first still holds the lock, and
    # Scheduler skips later runs while an execution is outstanding. The deadline sits under
    # Cloud Run's 300 s request timeout and above the pass budget.
    command = _committed_commands(existing=existing)["lemely-staging-sweep"]

    assert "--max-retry-attempts=0" in command
    assert "--attempt-deadline=90s" in command
    assert not [f for f in command if f.startswith(("--min-backoff", "--max-backoff"))]


@pytest.mark.parametrize("existing", [False, True], ids=["create", "update"])
def test_the_digest_keeps_its_retry_policy_exactly(existing: bool) -> None:
    command = _committed_commands(existing=existing)["lemely-staging-waitlist-digest"]

    flags = [f for f in command if f.startswith(("--max-", "--min-", "--attempt", "--clear-"))]
    # The digest sets no deadline: an update sends Scheduler's default, which it already has.
    reset = ["--clear-max-retry-duration", "--attempt-deadline=180s"] if existing else []
    assert flags == ["--max-retry-attempts=3", "--min-backoff=6m", "--max-backoff=30m", *reset]
    assert tuple(flags[:3]) == rc.RETRY_FLAGS


def test_the_sweep_pass_budget_fits_inside_the_attempt_deadline() -> None:
    from lemely.runtime.config import NotificationsSettings

    sweep = {j.id: j for j in rc.load_desired(COMMITTED)}["sweep"]
    deadline = int(sweep.attempt_deadline.rstrip("s"))  # type: ignore[union-attr]
    budget = NotificationsSettings().sweep_pass_budget_seconds
    # Headroom for the cold start, the proxy, and the one job that is mid-flight at the budget,
    # and a deadline short enough that a stuck pass is reported well inside the minute after next.
    assert budget + 30 <= deadline <= 100


def test_the_committed_sweep_job_is_required_and_the_digest_is_not() -> None:
    jobs = {j.id: j for j in rc.load_desired(COMMITTED)}
    assert jobs["sweep"].required is True
    assert jobs["waitlist-digest"].required is False


def test_a_missing_secret_for_a_required_job_is_an_error_not_a_warning() -> None:
    jobs = rc.load_desired(COMMITTED)

    with pytest.raises(rc.ReconcileError, match="SWEEP_JOBS_SECRET"):
        make_plan(jobs, [], {"WAITLIST_DIGEST_SECRET": "d"})  # type: ignore[arg-type]
    with pytest.raises(rc.ReconcileError, match="SWEEP_JOBS_SECRET"):
        make_plan(jobs, [], {**BOTH, "SWEEP_JOBS_SECRET": "   "})  # type: ignore[arg-type]
    # The digest stays optional: it is still skipped with a warning.
    only_digest = make_plan(jobs[:1], [], {})  # type: ignore[arg-type]
    assert only_digest.skipped == ["lemely-staging-waitlist-digest"]


def test_main_exits_nonzero_when_the_required_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WAITLIST_DIGEST_SECRET", "d")
    monkeypatch.delenv("SWEEP_JOBS_SECRET", raising=False)
    run = _list_runner([])

    assert rc.main([*ARGS, "--jobs-file", str(COMMITTED)], run=run) == 1

    assert "::error::" in capsys.readouterr().out
    assert [c[3] for c in run.commands] == ["list"]  # nothing was created


# -- the preflight that runs before the traffic switch ------------------------


def _preflight(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], **env: str | None
) -> tuple[int, str]:
    for name in ("SWEEP_JOBS_SECRET", "SWEEP_JOBS_SECRET_PREVIOUS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    code = rc.main(["--preflight", "--jobs-file", str(COMMITTED)])
    return code, capsys.readouterr().out


def test_the_preflight_passes_with_a_well_formed_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _out = _preflight(monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET)
    assert code == 0


def test_the_preflight_fails_when_the_secret_is_missing_or_blank(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for value in (None, "", "   "):
        code, out = _preflight(monkeypatch, capsys, SWEEP_JOBS_SECRET=value)
        assert code == 1, value
        assert "::error::" in out and "SWEEP_JOBS_SECRET" in out


@pytest.mark.parametrize(
    "bad",
    [
        "short-but-fine-chars",  # under 32 characters
        "x" * 31,
        "has a space " + "x" * 40,
        "x" * 40 + "\n",  # a stray trailing newline from a pasted secret
        "x" * 40 + ",comma",  # breaks gcloud's --headers syntax
        "x" * 40 + "é",  # not printable ASCII
        "x" * 40 + "\t",
    ],
)
def test_the_preflight_fails_on_a_malformed_secret_and_never_prints_it(
    bad: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _preflight(monkeypatch, capsys, SWEEP_JOBS_SECRET=bad)

    assert code == 1
    assert "::error::" in out
    assert bad.strip() not in out or not bad.strip()
    assert "x" * 10 not in out


def test_the_preflight_checks_the_previous_secret_when_one_is_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old = "old-secret-" + "y" * 40
    ok, _ = _preflight(
        monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET, SWEEP_JOBS_SECRET_PREVIOUS=old
    )
    blank, _ = _preflight(
        monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET, SWEEP_JOBS_SECRET_PREVIOUS=""
    )
    bad, out = _preflight(
        monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET, SWEEP_JOBS_SECRET_PREVIOUS="a b"
    )
    same, _ = _preflight(
        monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET, SWEEP_JOBS_SECRET_PREVIOUS=SWEEP_SECRET
    )

    assert (ok, blank) == (0, 0)  # optional: unset or blank means no rotation in progress
    assert bad == 1 and "SWEEP_JOBS_SECRET_PREVIOUS" in out
    assert same == 1  # a "previous" equal to the current one means the rotation was not staged


@pytest.mark.parametrize("value", [" ", "\n", "  \t ", "old-secret\n"])
def test_a_previous_secret_of_whitespace_is_set_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    # A whitespace-only PREVIOUS is not "unset": deploy.yml forwards it to the service as it is.
    # Only an empty value means no rotation is in progress.
    code, out = _preflight(
        monkeypatch, capsys, SWEEP_JOBS_SECRET=SWEEP_SECRET, SWEEP_JOBS_SECRET_PREVIOUS=value
    )

    assert code == 1 and "SWEEP_JOBS_SECRET_PREVIOUS" in out
    assert value.strip() == "" or value.strip() not in out


def test_the_plan_holds_a_required_secret_to_the_minimum_length() -> None:
    # The plan is the last check before the value is written into the Scheduler job, so it
    # enforces what the preflight enforces, even when the preflight was skipped.
    jobs = rc.load_desired(COMMITTED)
    short = "s" * (rc.REQUIRED_SECRET_MIN_LENGTH - 1)

    with pytest.raises(rc.ReconcileError, match="SWEEP_JOBS_SECRET") as caught:
        make_plan(jobs, [], {**BOTH, "SWEEP_JOBS_SECRET": short})  # type: ignore[arg-type]
    assert short not in str(caught.value)
    with pytest.raises(rc.ReconcileError, match="SWEEP_JOBS_SECRET"):
        make_plan(jobs, [], {**BOTH, "SWEEP_JOBS_SECRET": f" {SWEEP_SECRET}\n"})  # type: ignore[arg-type]
    exact = "s" * rc.REQUIRED_SECRET_MIN_LENGTH
    assert make_plan(jobs, [], {**BOTH, "SWEEP_JOBS_SECRET": exact}).create  # type: ignore[arg-type]


def _workflow_jobs() -> dict[str, dict[str, object]]:
    return yaml.safe_load(DEPLOY)["jobs"]


def _needs(job: Mapping[str, object]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)  # type: ignore[arg-type]


def test_the_preflight_runs_in_the_migrate_job_before_any_migration() -> None:
    # A bad sweep secret must stop the deploy before the schema moves and before any job that
    # ships code: a failed migrate job skips deploy-backend, edge-secret and deploy-frontend.
    jobs = _workflow_jobs()
    steps = jobs["migrate"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]  # type: ignore[union-attr]
    preflight = next(i for i, run in enumerate(runs) if "scheduler_reconcile.py --preflight" in run)
    migration = next(i for i, run in enumerate(runs) if "alembic upgrade head" in run)

    every_run = [
        str(step.get("run", ""))  # type: ignore[union-attr]
        for job in jobs.values()
        for step in job.get("steps", [])  # type: ignore[union-attr]
    ]
    assert preflight < migration
    assert sum("--preflight" in run for run in every_run) == 1  # once, here, not in deploy-backend
    for shipping in ("deploy-backend", "edge-secret", "deploy-frontend"):
        assert "migrate" in _needs(jobs[shipping]), shipping


def test_the_preflight_step_maps_the_secrets_and_prints_no_value() -> None:
    start = DEPLOY.index("scheduler_reconcile.py --preflight")
    step = DEPLOY[DEPLOY.rindex("      - name:", 0, start) : DEPLOY.index("\n\n", start)]

    assert DEPLOY.index("scheduler_reconcile.py --preflight") < DEPLOY.index("      - id: deploy")
    assert "SWEEP_JOBS_SECRET: ${{ secrets.SWEEP_JOBS_SECRET }}" in step
    assert "SWEEP_JOBS_SECRET_PREVIOUS: ${{ secrets.SWEEP_JOBS_SECRET_PREVIOUS }}" in step
    assert "echo" not in step.replace("::error", "")  # nothing in the step prints a value


def _cloud_run_env() -> dict[str, str]:
    steps = _workflow_jobs()["deploy-backend"]["steps"]
    deploy = next(step for step in steps if step.get("id") == "deploy")  # type: ignore[union-attr]
    lines = deploy["with"]["env_vars"].splitlines()  # type: ignore[index]
    return dict(line.split("=", 1) for line in lines if line)


def _sweep_job(**overrides: object) -> dict[str, object]:
    """The staging sweep job as ``gcloud scheduler jobs list --format=json`` reports it."""
    job: dict[str, object] = {
        **managed("staging", "sweep"),
        "state": "ENABLED",
        "httpTarget": {
            "uri": f"{HOST}/api/internal/jobs/sweep",
            "httpMethod": "POST",
            "headers": {"X-Cron-Secret": "an-older-secret-from-before-a-rotation"},
        },
    }
    job.update(overrides)
    return job


def _driver_ready(actual: list[dict[str, object]]) -> bool:
    return rc.sweep_driver_ready(
        rc.load_desired(COMMITTED), actual, environment="staging", host=HOST
    )


def test_the_loop_is_switched_off_only_once_a_working_sweep_job_exists() -> None:
    assert _driver_ready([_sweep_job()]) is True
    # A rotation changes only the job's header, which the check does not look at, so a
    # rotation never turns the loop back on.
    assert _driver_ready([_sweep_job(httpTarget={"uri": f"{HOST}/api/internal/jobs/sweep"})])


@pytest.mark.parametrize(
    "actual",
    [
        pytest.param([], id="first-cutover-no-job"),
        pytest.param([managed("staging", "waitlist-digest")], id="other-jobs-only"),
        pytest.param([_sweep_job(state="PAUSED")], id="paused"),
        pytest.param([_sweep_job(description="made by hand")], id="no-marker"),
        pytest.param(
            [_sweep_job(httpTarget={"uri": "https://lemelyig.com/api/internal/jobs/sweep"})],
            id="other-environment-host",
        ),
        pytest.param(
            [_sweep_job(httpTarget={"uri": f"{HOST}/api/internal/jobs/digest"})],
            id="other-path",
        ),
        pytest.param([_sweep_job(httpTarget=None)], id="not-http"),
        pytest.param(
            [
                {
                    **_sweep_job(),
                    "name": "projects/p/locations/us-central1/jobs/lemely-production-sweep",
                }
            ],
            id="other-environment-name",
        ),
    ],
)
def test_without_a_working_sweep_job_the_loop_stays_on(actual: list[dict[str, object]]) -> None:
    assert _driver_ready(actual) is False


def _driver_main(runner: object, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = rc.main(
        [
            "--sweep-driver",
            "--environment=staging",
            f"--host={HOST}",
            "--project=p",
            f"--jobs-file={COMMITTED}",
        ],
        run=runner,  # type: ignore[arg-type]
    )
    out, err = capsys.readouterr()
    return code, out, err


def test_the_driver_check_prints_the_setting_for_the_deploy_step(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def listing(jobs: list[dict[str, object]]) -> object:
        def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            assert list(command[:4]) == ["gcloud", "scheduler", "jobs", "list"]
            return subprocess.CompletedProcess(command, 0, json.dumps(jobs), "")

        return run

    assert _driver_main(listing([_sweep_job()]), capsys)[:2] == (0, "sweeper_enabled=false\n")
    code, out, err = _driver_main(listing([]), capsys)
    assert (code, out) == (0, "sweeper_enabled=true\n")
    assert "lemely-staging-sweep" in err


def test_a_failed_listing_keeps_the_loop_on_rather_than_leave_no_driver(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "PERMISSION_DENIED")

    code, out, err = _driver_main(broken, capsys)
    assert (code, out) == (0, "sweeper_enabled=true\n")
    assert "::warning::" in err


def _backend_steps() -> list[dict[str, object]]:
    return _workflow_jobs()["deploy-backend"]["steps"]  # type: ignore[return-value]


def test_the_deploy_decides_the_loop_setting_before_the_revision_is_made() -> None:
    steps = _backend_steps()
    ids = [step.get("id") for step in steps]
    decide = ids.index("sweep-driver")
    run = str(steps[decide]["run"])

    assert decide < ids.index("deploy")
    assert "scheduler_reconcile.py --sweep-driver" in run
    assert '>> "$GITHUB_OUTPUT"' in run
    assert "SWEEP_JOBS_SECRET" not in str(steps[decide])  # the decision never reads a secret
    value = _cloud_run_env()["LEMELY_NOTIFICATIONS__SWEEPER_ENABLED"]
    assert value == "${{ steps.sweep-driver.outputs.sweeper_enabled }}"


@pytest.mark.parametrize(("decided", "enabled"), [("false", False), ("true", True)])
def test_both_decisions_reach_the_service_as_its_setting(
    decided: str, enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read through the real settings model, so a renamed field or env var name goes red here.
    from lemely.runtime.config import Settings

    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", decided)
    assert Settings().notifications.sweeper_enabled is enabled


def test_a_failed_reconcile_with_the_loop_off_names_the_missing_driver_and_the_fix() -> None:
    steps = _backend_steps()
    ids = [step.get("id") for step in steps]
    reconcile = ids.index("reconcile")
    report = next(
        i for i, step in enumerate(steps) if "billing sweep driver absent" in str(step.get("run"))
    )
    step = steps[report]

    assert reconcile < report
    condition = str(step["if"])
    assert "failure()" in condition
    assert "steps.reconcile.outcome == 'failure'" in condition
    assert "steps.sweep-driver.outputs.sweeper_enabled == 'false'" in condition
    run = str(step["run"])
    assert "gcloud run services update" in run
    assert "LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=true" in run
    assert "exit 1" in run


def test_the_previous_secret_reaches_the_service_as_its_setting() -> None:
    line = "LEMELY_NOTIFICATIONS__JOBS_SECRET_PREVIOUS=${{ secrets.SWEEP_JOBS_SECRET_PREVIOUS }}"
    assert line in DEPLOY
    assert DEPLOY.index(line) < DEPLOY.index("Verify the serving revision runs this commit")
