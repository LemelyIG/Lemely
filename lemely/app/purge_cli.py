"""``lemely admin purge-users``: clear a database of non-allow-listed accounts and their files.

Dry-run by default: a count summary first, then rows per table, the kept accounts whose data is
affected, and the full list of accounts that would be deleted. ``--execute`` deletes the database
rows in one transaction (children first) and, only once that has committed, the storage objects
and then the matching Supabase Auth users. The logic is in :mod:`lemely.db.user_purge`; this
module is the command's printing, flags and safety rails.

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
* The database goes **first**. If it fails (a foreign key, a lost connection) the transaction
  rolls back and no storage object and no Auth user has been touched, so no row is left pointing
  at a deleted file. Reachability of every bucket is proven before that step.
* Objects go second, then Auth. Both are idempotent (an object or user already gone is success)
  and list every failure; the exit code is 1 if any step failed. If an object fails, Auth is
  skipped (reported as such), so the purged accounts stay listed as Auth orphans and a re-run
  finds their key prefixes again (``uploads/{id}/``, ``teacher/{id}/``, ``{id}/``) and finishes
  the job. A failed key outside those folders is never retried: it is printed for deletion by
  hand.
* If the Supabase Auth listing fails, ``--execute`` stops before any change; a dry run warns.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import click
from sqlalchemy.exc import SQLAlchemyError

from lemely.auth.gotrue import GoTrueAdmin, HttpGoTrueAdmin
from lemely.db.session import get_engine
from lemely.db.user_purge import (
    ObjectPurgeReport,
    PurgeError,
    PurgePlan,
    add_orphan_prefixes,
    auth_targets,
    check_schema_at_head,
    classify_environment,
    discover_unreferenced,
    execute_purge,
    keys_a_rerun_will_miss,
    plan_purge,
    purge_auth_users,
    purge_objects,
    storage_config_problems,
    user_prefixes,
)

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


def _unreachable_buckets(settings: Settings, backend: ObjectDeleter) -> list[str]:
    """Why a bucket does not answer, using only object permissions (no ``buckets.get``).

    Each of the three buckets is asked for at most one object, which is what deleting and listing
    need and all the runtime account's ``roles/storage.objectAdmin`` is guaranteed to grant. A
    backend with no probe (an injected test double) has nothing to prove.
    """
    probe = getattr(backend, "probe_bucket", None)
    if probe is None or settings.storage.backend != "gcs":
        return []
    problems: list[str] = []
    for kind, bucket in _bucket_names(settings).items():
        try:
            probe(bucket)
        except Exception as exc:
            problems.append(f"{kind} bucket {bucket!r} not reachable: {type(exc).__name__}: {exc}")
    return problems


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
    object_backend: ObjectDeleter = storage if storage is not None else _storage_backend(settings)
    buckets = _bucket_names(settings)
    if storage is None and not storage_problems:
        # Dry run included, so a dry run proves what --execute needs.
        storage_problems = _unreachable_buckets(settings, object_backend)
        if execute and storage_problems:
            raise click.ClickException(
                "Storage is not reachable, so nothing was changed:\n  - "
                + "\n  - ".join(storage_problems)
            )

    engine = get_engine(settings)
    object_report: ObjectPurgeReport | None = None
    sweep_note = ""
    auth_note = ""
    auth_report = None
    targets: list[tuple[uuid.UUID, str]] = []
    orphans: list[tuple[uuid.UUID, str]] = []
    stage = "plan"
    try:
        with engine.begin() as conn:
            check_schema_at_head(conn)
            plan = plan_purge(
                conn, domains, include_unverified_allowlisted=include_unverified_allowlisted
            )
            remaining = {a.id for a in plan.kept_verified + plan.unverified_allowlisted}
            if include_unverified_allowlisted:
                remaining -= set(plan.delete_ids)
            # Auth users to remove: the purged ids plus orphans left by an earlier run. Listed
            # before the rows go because an orphan's key prefixes are how a re-run finds the
            # objects whose rows an earlier run already deleted.
            try:
                targets = auth_targets(
                    auth_admin,
                    delete_ids=plan.delete_ids,
                    remaining_ids=remaining,
                    keep_domains=domains,
                    include_unverified_allowlisted=include_unverified_allowlisted,
                )
            except Exception as exc:
                if execute:
                    # Without the listing the Auth users cannot be removed, and deleting only the
                    # rows and files would leave their sessions live.
                    raise click.ClickException(
                        "Could not list the Supabase Auth users, so nothing was changed: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                auth_note = f"Supabase Auth step failed: {type(exc).__name__}: {exc}"
                targets = [(i, "") for i in plan.delete_ids]
            delete_set = set(plan.delete_ids)
            orphans = [(uid, email) for uid, email in targets if uid not in delete_set]
            add_orphan_prefixes(plan, [uid for uid, _ in orphans])
            if plan.prefixes and (execute or not storage_problems):
                try:
                    discover_unreferenced(object_backend, buckets, plan)
                except Exception as exc:
                    if execute:
                        raise click.ClickException(
                            f"Could not list the purged users' storage prefixes, so nothing "
                            f"was changed: {type(exc).__name__}: {exc}"
                        ) from exc
                    sweep_note = f"Prefix sweep skipped: {type(exc).__name__}: {exc}"
            if execute and plan.to_delete:
                execute_purge(conn, plan)
                stage = "commit"
    except PurgeError as exc:
        raise click.ClickException(str(exc)) from exc
    except SQLAlchemyError as exc:
        detail = (str(getattr(exc, "orig", exc)).splitlines() or [""])[0]
        if stage == "commit":
            # Every statement ran; the failure came while committing, and the server may have
            # committed anyway. Storage and Auth were never reached either way.
            raise click.ClickException(
                "The database commit did not report success, so it is unknown whether the rows "
                "are gone (no storage object or Auth user was touched). Run a dry run to see "
                f"what remains before re-running: {type(exc).__name__}: {detail}"
            ) from exc
        raise click.ClickException(
            "The database step failed and was rolled back, so no row, storage object or Auth "
            f"user was deleted: {type(exc).__name__}: {detail}"
        ) from exc
    db_done = execute and bool(plan.to_delete)

    # The rows are committed. Storage next (idempotent), then Auth only if every object went, so
    # a failed object leaves its owner listed as an Auth orphan for the re-run to sweep.
    if execute and plan.objects:
        object_report = purge_objects(object_backend, buckets, plan.objects)
    objects_blocked = bool(object_report and object_report.failed)
    if execute and not objects_blocked:
        auth_report = purge_auth_users(auth_admin, targets)
    auth_skipped_reason = (
        "an object failed to delete; the re-run deletes the Auth users"
        if execute and auth_report is None
        else None
    )
    by_hand = (
        keys_a_rerun_will_miss(object_report, buckets, [uid for uid, _ in targets])
        if object_report
        else []
    )
    orphan_folders = {
        uid: [f"{buckets[kind]}/{prefix}" for kind, prefix in user_prefixes(uid)]
        for uid, _ in orphans
    }

    exit_code = 1 if objects_blocked or (auth_report and auth_report.failed) else 0
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
                    "authDeleted": len(auth_report.deleted) if auth_report else 0,
                    "authSkipped": auth_skipped_reason is not None,
                    "authSkippedReason": auth_skipped_reason,
                    "orphans": [
                        {"id": str(uid), "email": email, "folders": orphan_folders[uid]}
                        for uid, email in orphans
                    ],
                    "authFailed": [list(f) for f in auth_report.failed] if auth_report else [],
                    "authError": auth_note or None,
                    "objects": {k: len(v) for k, v in plan.objects.items()},
                    "objectsKeptShared": plan.objects_kept_shared,
                    "objectsFailed": [list(f) for f in object_report.failed]
                    if object_report
                    else [],
                    "objectsFailedByHand": [list(k) for k in by_hand],
                    "storageProblems": storage_problems,
                },
                indent=2,
            )
        )
        return exit_code

    _print_plan(plan, execute=execute, storage_problems=storage_problems)
    if sweep_note:
        click.echo(sweep_note, err=True)
    if orphans:
        click.echo(
            f"Auth users with no account row (orphans), whose folders are swept: {len(orphans)}"
        )
        for uid, email in orphans:
            click.echo(f"  {uid} {email}".rstrip())
            for folder in orphan_folders[uid]:
                click.echo(f"      {folder}")
    if not execute:
        click.echo(f"Supabase Auth users that would be deleted: {len(targets)}")
    elif auth_report is not None:
        click.echo(f"Supabase Auth users deleted: {len(auth_report.deleted)}")
    else:
        click.echo(f"Supabase Auth users deleted: skipped ({auth_skipped_reason})")
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
                "Some objects could not be deleted. The database rows are already gone and the "
                "Auth users were kept so the re-run can sweep the per-user folders again. Fix "
                "the cause and re-run the same command.",
                err=True,
            )
        if by_hand:
            click.echo(
                "Delete these by hand: they sit outside the per-user folders a re-run sweeps, so "
                "it will not retry them:",
                err=True,
            )
            for bucket, key in by_hand:
                click.echo(f"  {bucket}/{key}", err=True)
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
