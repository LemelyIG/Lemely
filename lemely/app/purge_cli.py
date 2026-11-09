"""``lemely admin purge-users``: clear a database of non-allow-listed accounts and their files.

Dry-run by default: a count summary first, then rows per table, the kept accounts whose data is
affected, and the full list of accounts that would be deleted. ``--execute`` deletes the storage
objects first, then the database rows in one transaction (children first), then the matching
Supabase Auth users. The logic is in :mod:`lemely.db.user_purge`; this module is the command's
printing, flags and safety rails.

**Safety rails.**

* It refuses a production-looking target (:func:`~lemely.db.user_purge.classify_environment`),
  and a remote target it cannot recognise as staging, unless ``--i-know-this-is-production`` is
  given.
* It refuses unless the database is at Alembic head.
* Outside a local database ``--execute`` needs the ``gcs`` backend and the three buckets set
  explicitly, each naming the detected environment, and every bucket must answer before anything
  is deleted. A dry run prints the same problems as a warning.
* It never deletes an account on a keep-domain with a verified email. An unverified one is kept
  too unless ``--include-unverified-allowlisted``.
* Objects go **first**: if any object fails to delete, no database row is touched, so a plain
  re-run retries. A missing object counts as done.
* The Auth step is idempotent (a user already gone is success) and lists every failure; the exit
  code is 1 if any step failed, and a re-run finishes the job.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import click

from lemely.auth.gotrue import GoTrueAdmin, HttpGoTrueAdmin
from lemely.db.session import get_engine
from lemely.db.user_purge import (
    ObjectPurgeReport,
    PurgeError,
    PurgePlan,
    auth_targets,
    check_schema_at_head,
    classify_environment,
    discover_unreferenced,
    execute_purge,
    plan_purge,
    purge_auth_users,
    purge_objects,
    storage_config_problems,
)
from lemely.io.storage import check_storage, check_tutor_evidence_storage

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from lemely.db.user_purge import Account, ObjectDeleter
    from lemely.runtime.config import Settings


PRIVILEGED_ROLES = frozenset({"platform_admin", "school_admin"})


def _account_lines(accounts: Sequence[Account]) -> list[str]:
    return [f"  {a.id}  {a.email}  {a.role}  {a.created_at.isoformat()}" for a in accounts]


def _print_plan(plan: PurgePlan, *, execute: bool, storage_problems: Sequence[str]) -> None:
    unverified_note = (
        "will be DELETED (--include-unverified-allowlisted)"
        if plan.include_unverified_allowlisted
        else "kept"
    )
    verb = "DELETED" if execute else "to delete"
    other_rows = sum(n for t, n in plan.deleted_rows.items() if t != "users")
    click.echo("=== SUMMARY ===")
    click.echo(f"Keep domains: {', '.join(plan.keep_domains)}")
    click.echo(f"Accounts kept (verified, allow-listed): {len(plan.kept_verified)}")
    click.echo(
        f"Allow-listed but UNVERIFIED accounts ({unverified_note}): "
        f"{len(plan.unverified_allowlisted)}"
    )
    click.echo(f"Accounts {verb}: {len(plan.to_delete)}")
    privileged = [a for a in plan.to_delete if a.role in PRIVILEGED_ROLES]
    if privileged:
        click.echo(
            f"!!! {len(privileged)} PRIVILEGED ACCOUNT(S) IN THE DELETE LIST "
            "(platform_admin / school_admin): they lose console access."
        )
        for line in _account_lines(privileged):
            click.echo(line)
    click.echo(f"Dependent rows {verb}, across {len(plan.deleted_rows)} tables: {other_rows}")
    click.echo("Waitlist applicants: never touched.")
    object_total = sum(len(keys) for keys in plan.objects.values())
    click.echo(f"Storage objects {verb}: {object_total}")
    for kind, keys in plan.objects.items():
        click.echo(f"  {kind}: {len(keys)}")
    if plan.unreferenced_objects:
        click.echo(
            f"  of which referenced by no row (found by prefix): {plan.unreferenced_objects}"
        )
    if plan.objects_kept_shared:
        click.echo(f"  kept (shared with a surviving account): {plan.objects_kept_shared}")
    if storage_problems:
        click.echo("!!! STORAGE CONFIGURATION: --execute would refuse to run:")
        for problem in storage_problems:
            click.echo(f"  - {problem}")
    if plan.kept_impacts:
        click.echo("=== KEPT ACCOUNTS WHOSE DATA IS AFFECTED (the rows go with their owner) ===")
        for impact in plan.kept_impacts:
            click.echo(
                f"  {impact.kept_email}: {impact.rows} row(s) in {impact.table}.{impact.column}"
            )
    if plan.deleted_rows:
        click.echo("=== ROWS PER TABLE (accounts plus their dependent data) ===")
        for table, count in plan.deleted_rows.items():
            click.echo(f"  {table}: {count}")
    if plan.detached_rows:
        click.echo("=== ROWS KEPT WITH A REFERENCE TO A DELETED ACCOUNT CLEARED ===")
        for column, count in plan.detached_rows.items():
            click.echo(f"  {column}: {count}")
    if plan.unverified_allowlisted:
        click.echo("=== UNVERIFIED ALLOW-LISTED ACCOUNTS ===")
        for line in _account_lines(plan.unverified_allowlisted):
            click.echo(line)
    click.echo(f"=== ACCOUNTS {verb.upper()} (id, email, role, created_at) ===")
    for line in _account_lines(plan.to_delete):
        click.echo(line)


def _bucket_names(settings: Settings) -> dict[str, str]:
    storage = settings.storage
    return {
        "uploads": storage.bucket,
        "avatars": storage.avatar_bucket,
        "tutor_evidence": storage.tutor_evidence_bucket,
    }


def _storage_backend(settings: Settings) -> ObjectDeleter:
    """The backend the app builds (``lemely.web.deps.get_storage_backend``), from ``settings``."""
    from lemely.io.storage_gcs import GcsStorageBackend
    from lemely.io.storage_local import LocalFileStorageBackend

    storage = settings.storage
    if storage.backend == "gcs":
        return GcsStorageBackend(
            project=storage.gcs_project,
            tutor_evidence_bucket=storage.tutor_evidence_bucket,
            project_number=storage.gcs_project_number,
        )
    return LocalFileStorageBackend(settings.paths.output_dir / "storage")


def _check_buckets_reachable(settings: Settings) -> None:
    """Fail before any deletion unless the real buckets answer with the configured credentials."""
    if settings.storage.backend != "gcs":
        return
    for ok, detail in (
        check_storage(settings, no_network=False),
        check_tutor_evidence_storage(settings, no_network=False),
    ):
        if not ok:
            raise click.ClickException(
                f"Storage is not reachable, so nothing was changed: {detail}"
            )


def purge_users_command(
    settings: Settings,
    *,
    keep_domains: tuple[str, ...],
    execute: bool,
    include_unverified_allowlisted: bool,
    allow_production: bool,
    json_output: bool,
    allow_unrecognised: bool = False,
    admin: GoTrueAdmin | None = None,
    storage: ObjectDeleter | None = None,
) -> int:
    """Run the purge and return the process exit code (0 ok, 1 if any step failed)."""
    domains = keep_domains or tuple(settings.access.allowed_email_domains)
    if not domains:
        raise click.UsageError(
            "No keep domain: pass --keep-domain (for example lemelyig.com) or set "
            "[access] allowed_email_domains."
        )
    verdict = classify_environment(settings, os.environ)
    if not verdict.safe:
        click.echo(
            f"Target looks like {verdict.kind.upper()} (database host {verdict.db_host}):",
            err=True,
        )
        for reason in verdict.reasons:
            click.echo(f"  - {reason}", err=True)
        # Two different refusals, two different flags: the production flag passes only a target
        # positively identified as production, never one the tool could not recognise.
        if verdict.kind == "production" and allow_production:
            click.echo("--i-know-this-is-production given: continuing.", err=True)
        elif verdict.kind == "unknown" and allow_unrecognised:
            click.echo("--target-is-unrecognised given: continuing.", err=True)
        elif verdict.kind == "unknown":
            raise click.ClickException(
                "Refusing to purge a target this tool cannot recognise as local, staging or "
                "production (a mistyped URL looks like this). Check LEMELY_DATABASE__URL and "
                "LEMELY_SUPABASE__URL; if the target is right, pass --target-is-unrecognised. "
                "--i-know-this-is-production does not cover it."
            )
        else:
            raise click.ClickException(
                "Refusing to purge a production target. If you really mean to run it against "
                "production, pass --i-know-this-is-production."
            )
    auth_admin = admin if admin is not None else HttpGoTrueAdmin(settings)
    storage_problems = storage_config_problems(settings, verdict) if storage is None else []
    if execute:
        if storage_problems:
            raise click.ClickException(
                "Storage is not configured safely, so nothing was changed:\n  - "
                + "\n  - ".join(storage_problems)
            )
        if admin is None and settings.supabase.service_role_key is None:
            raise click.ClickException(
                "No Supabase service-role key (LEMELY_SUPABASE__SERVICE_ROLE_KEY): the Auth "
                "users could not be deleted, so nothing was changed."
            )
        if storage is None:
            _check_buckets_reachable(settings)
    object_backend: ObjectDeleter = storage if storage is not None else _storage_backend(settings)
    buckets = _bucket_names(settings)

    engine = get_engine(settings)
    object_report: ObjectPurgeReport | None = None
    sweep_note = ""
    try:
        with engine.begin() as conn:
            check_schema_at_head(conn)
            plan = plan_purge(
                conn, domains, include_unverified_allowlisted=include_unverified_allowlisted
            )
            if plan.to_delete and (execute or not storage_problems):
                try:
                    discover_unreferenced(object_backend, buckets, plan)
                except Exception as exc:
                    if execute:
                        raise click.ClickException(
                            f"Could not list the purged users' storage prefixes, so nothing "
                            f"was changed: {type(exc).__name__}: {exc}"
                        ) from exc
                    sweep_note = f"Prefix sweep skipped: {type(exc).__name__}: {exc}"
            remaining = {a.id for a in plan.kept_verified + plan.unverified_allowlisted}
            if include_unverified_allowlisted:
                remaining -= set(plan.delete_ids)
            if execute and plan.objects:
                # Objects first: a failure leaves every row in place, so a re-run retries.
                object_report = purge_objects(object_backend, buckets, plan.objects)
            if execute and plan.to_delete and not (object_report and object_report.failed):
                execute_purge(conn, plan)
            db_done = execute and plan.to_delete and not (object_report and object_report.failed)
    except PurgeError as exc:
        raise click.ClickException(str(exc)) from exc

    objects_blocked = bool(object_report and object_report.failed)
    auth_note = ""
    auth_report = None
    targets: list[tuple[uuid.UUID, str]] = []
    if not objects_blocked:
        try:
            targets = auth_targets(
                auth_admin,
                delete_ids=plan.delete_ids,
                remaining_ids=remaining,
                keep_domains=domains,
                include_unverified_allowlisted=include_unverified_allowlisted,
            )
            if execute:
                auth_report = purge_auth_users(auth_admin, targets)
        except Exception as exc:
            auth_note = f"Supabase Auth step failed: {type(exc).__name__}: {exc}"

    exit_code = (
        1
        if objects_blocked or (auth_note and execute) or (auth_report and auth_report.failed)
        else 0
    )
    if json_output:
        click.echo(
            json.dumps(
                {
                    "executed": execute,
                    "databaseDeleted": bool(db_done),
                    "keepDomains": list(domains),
                    "deleted": [
                        {
                            "id": str(a.id),
                            "email": a.email,
                            "role": a.role,
                            "createdAt": a.created_at.isoformat(),
                        }
                        for a in plan.to_delete
                    ],
                    "privilegedDeleted": [
                        str(a.id) for a in plan.to_delete if a.role in PRIVILEGED_ROLES
                    ],
                    "unverifiedAllowlisted": [str(a.id) for a in plan.unverified_allowlisted],
                    "deletedRows": plan.deleted_rows,
                    "detachedRows": plan.detached_rows,
                    "keptImpacts": [
                        {
                            "table": i.table,
                            "column": i.column,
                            "email": i.kept_email,
                            "rows": i.rows,
                        }
                        for i in plan.kept_impacts
                    ],
                    "authTargets": len(targets),
                    "authFailed": [list(f) for f in auth_report.failed] if auth_report else [],
                    "authError": auth_note or None,
                    "objects": {k: len(v) for k, v in plan.objects.items()},
                    "objectsKeptShared": plan.objects_kept_shared,
                    "objectsFailed": [list(f) for f in object_report.failed]
                    if object_report
                    else [],
                    "storageProblems": storage_problems,
                },
                indent=2,
            )
        )
        return exit_code

    _print_plan(plan, execute=execute, storage_problems=storage_problems)
    if sweep_note:
        click.echo(sweep_note, err=True)
    click.echo(
        f"Supabase Auth users {'deleted' if execute else 'that would be deleted'}: {len(targets)}"
    )
    if auth_note:
        click.echo(auth_note, err=True)
    if object_report is not None:
        click.echo(
            f"Storage objects deleted: {sum(object_report.deleted.values())} "
            f"failed={len(object_report.failed)}"
        )
        for label, error in object_report.failed:
            click.echo(f"  FAILED {label}: {error}", err=True)
        if object_report.failed:
            click.echo(
                "Some objects could not be deleted, so NO database row was touched. "
                "Fix the cause and re-run the same command.",
                err=True,
            )
    if auth_report is not None:
        click.echo(
            f"  deleted={len(auth_report.deleted)} already_gone={len(auth_report.already_gone)} "
            f"failed={len(auth_report.failed)}"
        )
        for label, error in auth_report.failed:
            click.echo(f"  FAILED {label}: {error}", err=True)
    if not execute:
        click.echo("Dry run: nothing was deleted. Re-run with --execute to delete.")
    elif db_done:
        click.echo("Done.")
    return exit_code


__all__ = ["purge_users_command"]
