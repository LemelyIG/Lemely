"""Staging purge: remove every account outside the allow-list, with its data.

``lemely admin purge-users`` (``lemely/app/purge_cli.py``) is the only caller. It exists to clear
a pre-launch staging database of the accounts that signed up before the access gate, keeping
only the allow-listed team. It is destructive and, by design, hard to point at the wrong place.

**Which accounts go.** An account is *kept* when its email domain equals a keep-domain **and** its
inbox was proven (``users.email_verified_at`` set). A keep-domain account that was never verified
is listed separately and is also kept, unless the caller asks for it
(``include_unverified_allowlisted``): that address could have been claimed by anyone. Every other
account goes.

**FK-safe deletion without a hand-kept table list.** The foreign keys that reference ``users`` (and
those that reference the tables those rows live in, and so on) are read from ``pg_constraint`` at
run time, so a migration that adds a table is covered without editing this module. For each
referencing column the database's own rule decides:

* ``ON DELETE CASCADE``: the dependent rows go with the user; they are counted, not deleted by us.
* ``ON DELETE SET NULL``: the row survives with the column cleared; counted as *detached*.
* ``NO ACTION`` / ``RESTRICT`` and the column is nullable: we ``UPDATE ... SET col = NULL``
  (an audit pointer such as ``review_queue.resolved_by``; deleting the row would destroy another
  user's data).
* ``NO ACTION`` / ``RESTRICT`` and the column is ``NOT NULL`` (a row that cannot exist without
  the user, such as a class's teacher): the rows are deleted, children first, recursing into
  whatever references them.

Rows reachable by more than one path are counted once (by ``ctid``). The deletes run in a single
transaction owned by the caller, so a failure anywhere rolls the whole purge back.

**Not touched here:** object storage (uploaded scans, avatars), and tables keyed by email rather
than by a user foreign key (``waitlist_applicants``, auth cooldowns).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlsplit

import sqlalchemy as sa

from lemely.core.access import is_allowed_email
from lemely.core.object_keys import sibling_scheme_key

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from sqlalchemy.engine import Connection

    from lemely.auth.gotrue import GoTrueAdmin
    from lemely.runtime.config import Settings

#: Supabase project refs (docs/ci-cd.md). The ref is in the project's API URL and in the
#: session-pooler username, which is how a database URL is recognised without connecting to it.
PRODUCTION_PROJECT_REFS: tuple[str, ...] = ("ynrmqjiqcvmcakondjbp",)
STAGING_PROJECT_REFS: tuple[str, ...] = ("respcqftujbbyvsbkibk",)
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "host.docker.internal"})

_MAX_DEPTH = 12

#: Tables the purge must never reach. Waitlist applicants are not users (no foreign key to
#: ``users``); if a future migration linked one, the walk stops instead of deleting it.
PROTECTED_TABLES: frozenset[str] = frozenset({"waitlist_applicants"})


class PurgeError(RuntimeError):
    """The purge cannot proceed safely (unsupported schema shape, runaway recursion)."""


# ---------------------------------------------------------------------------
# Environment safety
# ---------------------------------------------------------------------------

EnvironmentKind = Literal["local", "staging", "production", "unknown"]


@dataclass(frozen=True, slots=True)
class EnvironmentVerdict:
    """What the configured database and Supabase project look like."""

    kind: EnvironmentKind
    reasons: tuple[str, ...]
    db_host: str

    @property
    def safe(self) -> bool:
        """Only a local database or a known staging project is safe to purge."""
        return self.kind in ("local", "staging")


def _url_host_and_user(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), (parts.username or "").lower()


def classify_environment(
    settings: Settings, env: Mapping[str, str] | None = None
) -> EnvironmentVerdict:
    """Classify the configured target, **failing closed**.

    Production if *any* signal says so (a production Supabase ref in the database or API URL, or a
    ``production`` bucket or service name; the app origin is not a signal, its default is the
    production one). Otherwise local when both
    the database and the Supabase API are on this machine, staging when both name the staging
    project (or the API is local), and **unknown** for anything else: a remote database with no
    staging marker is refused rather than assumed harmless.
    """
    env = env or {}
    db_host, db_user = _url_host_and_user(settings.database.url)
    sb_host, _ = _url_host_and_user(settings.supabase.url)
    db_blob = f"{db_host} {db_user}"
    production: list[str] = []
    for ref in PRODUCTION_PROJECT_REFS:
        if ref in db_blob:
            production.append(f"the database URL names the production project {ref}")
        if ref in sb_host:
            production.append(f"the Supabase URL names the production project {ref}")
    positively_production = bool(production)
    for name, bucket in (
        ("uploads", settings.storage.bucket),
        ("avatars", settings.storage.avatar_bucket),
        ("tutor evidence", settings.storage.tutor_evidence_bucket),
    ):
        if bucket and "production" in str(bucket).lower():
            production.append(f"the {name} bucket is {bucket!r}")
    service = env.get("K_SERVICE", "")
    if "production" in service.lower():
        production.append(f"this is Cloud Run service {service}")
    if production and positively_production:
        return EnvironmentVerdict("production", tuple(production), db_host)
    if production:
        # Bucket or service names say production but neither the database nor the Supabase
        # project does: a mixed target. It is never "production" (that would let the production
        # flag pass the storage check on a staging database); it is refused as unrecognised.
        return EnvironmentVerdict(
            "unknown",
            (
                *production,
                "but neither the database nor the Supabase URL names the production project",
            ),
            db_host,
        )

    db_local = db_host in _LOCAL_HOSTS
    sb_local = sb_host in _LOCAL_HOSTS
    if db_local and sb_local:
        return EnvironmentVerdict(
            "local", ("database and Supabase API are on this machine",), db_host
        )
    db_staging = any(ref in db_blob for ref in STAGING_PROJECT_REFS)
    sb_staging = any(ref in sb_host for ref in STAGING_PROJECT_REFS)
    if (db_staging or db_local) and (sb_staging or sb_local) and (db_staging or sb_staging):
        return EnvironmentVerdict("staging", ("the target names the staging project",), db_host)
    reasons = []
    if not (db_local or db_staging):
        reasons.append(
            f"database host {db_host or '(none)'} is not local or a known staging project"
        )
    if not (sb_local or sb_staging):
        reasons.append(
            f"Supabase host {sb_host or '(none)'} is not local or a known staging project"
        )
    if not reasons:
        reasons.append("the database and the Supabase project are not the same environment")
    return EnvironmentVerdict("unknown", tuple(reasons), db_host)


# ---------------------------------------------------------------------------
# Storage objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StorageColumn:
    """A database column that holds an object key, and the bucket (a logical kind) it lives in."""

    table: str
    column: str
    bucket: str
    #: An upload's ``mark_scheme.pdf`` sits next to it under the same prefix (no row of its own).
    sibling_scheme: bool = False


#: Every column that names a stored object. ``tests/test_user_purge.py`` scans the migrated schema
#: and fails if a path-like column exists that is not listed here, so a new one cannot be missed.
STORAGE_COLUMNS: tuple[StorageColumn, ...] = (
    StorageColumn("uploads", "storage_path", "uploads", sibling_scheme=True),
    StorageColumn("teacher_papers", "storage_path", "uploads"),
    StorageColumn("teacher_papers", "scheme_storage_path", "uploads"),
    StorageColumn("users", "avatar_path", "avatars"),
    StorageColumn("tutor_evidence_files", "storage_path", "tutor_evidence"),
)


#: Every uuid column that has no foreign key (and is not a primary key), with why the purge's walk
#: need not handle it. ``tests/test_user_purge.py`` scans the migrated schema and fails on a column
#: missing here, so a new id column that names a user cannot slip past the purge unnoticed.
NON_FK_UUID_COLUMNS: dict[tuple[str, str], str] = {
    ("friendships", "pair_low"): "derived copy of requester_id/addressee_id; the row is deleted "
    "with either user (both foreign keys cascade)",
    ("friendships", "pair_high"): "derived copy of requester_id/addressee_id; the row is deleted "
    "with either user (both foreign keys cascade)",
    ("tutoring_admin_access", "tutor_profile_id"): "append-only admin read log (tutoring SPEC "
    "SC-23), kept by design: ids of profiles, bookings, evidence and reports, no account data; "
    "admin_user_id is SET NULL",
    ("tutoring_admin_access", "booking_id"): "same append-only log",
    ("tutoring_admin_access", "evidence_id"): "same append-only log",
    ("tutoring_admin_access", "report_id"): "same append-only log",
    ("ai_detection_removal_audit_log", "source_id"): "id of a review_queue row, written once by "
    "migration 0037; no user data",
}


def collect_objects(
    conn: Connection, doomed: Mapping[str, set[str]]
) -> tuple[dict[str, list[str]], int, dict[str, set[str]]]:
    """Object keys only the doomed rows reference, how many were kept, and every protected key.

    Read **before** the rows are deleted. A key is returned only when no surviving row references
    it (in any listed column of the same bucket, a surviving upload's ``mark_scheme.pdf`` sibling
    included); a key shared with a kept user's row is left alone and counted in the second value.
    """
    candidates: dict[str, set[str]] = defaultdict(set)
    protected: dict[str, set[str]] = defaultdict(set)
    quote = conn.dialect.identifier_preparer.quote
    for col in STORAGE_COLUMNS:
        table, column = quote(col.table), quote(col.column)
        rows = conn.execute(
            sa.text(f"SELECT ctid::text, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
        )
        for ctid, key in rows:
            keys = {key}
            if col.sibling_scheme:
                keys.add(sibling_scheme_key(key))
            target = candidates if ctid in doomed.get(col.table, set()) else protected
            target[col.bucket].update(keys)
    objects = {
        b: sorted(k - protected[b]) for b, k in sorted(candidates.items()) if k - protected[b]
    }
    shared = sum(len(k & protected[b]) for b, k in candidates.items())
    return objects, shared, dict(protected)


def _prefixes(
    conn: Connection, user_ids: Iterable[uuid.UUID], doomed: Mapping[str, set[str]]
) -> dict[str, list[str]]:
    """Per-user key prefixes (the layouts the upload routes write) to sweep for unreferenced files.

    Uploads live under ``uploads/{user}/`` and ``teacher/{user}/``, avatars under ``{user}/``,
    and tutor evidence under ``tutor-evidence/{tutor_profile}/``.
    """
    prefixes: dict[str, list[str]] = {"uploads": [], "avatars": [], "tutor_evidence": []}
    for user_id in user_ids:
        prefixes["uploads"] += [f"uploads/{user_id}/", f"teacher/{user_id}/"]
        prefixes["avatars"].append(f"{user_id}/")
    profile_ctids = sorted(doomed.get("tutor_profiles", set()))
    if profile_ctids:
        profiles = _tbl("tutor_profiles", ["id"])
        for (profile_id,) in conn.execute(sa.select(profiles.c.id).where(_CTID.in_(profile_ctids))):
            prefixes["tutor_evidence"].append(f"tutor-evidence/{profile_id}/")
    return {kind: sorted(p) for kind, p in prefixes.items() if p}


class ObjectLister(Protocol):
    """Optional storage capability: the keys under a prefix (both real backends have it)."""

    def list_objects(self, bucket: str, prefix: str) -> list[str]:
        """Return every object key in ``bucket`` that starts with ``prefix``."""
        ...


def discover_unreferenced(
    storage: object,
    buckets: Mapping[str, str],
    plan: PurgePlan,
) -> int:
    """Add objects under the purged users' prefixes that no row references to ``plan.objects``.

    An object can outlive its row (a failed delete, an interrupted upload). Keys a surviving row
    references are never added. Returns how many were added; a backend that cannot list adds none.
    """
    lister = getattr(storage, "list_objects", None)
    if lister is None:
        return 0
    added = 0
    for kind, prefixes in plan.prefixes.items():
        known = set(plan.objects.get(kind, []))
        protected = plan.protected_keys.get(kind, set())
        for prefix in prefixes:
            for key in lister(buckets[kind], prefix):
                if key not in known and key not in protected:
                    known.add(key)
                    added += 1
        if known:
            plan.objects[kind] = sorted(known)
    plan.unreferenced_objects += added
    return added


class ObjectDeleter(Protocol):
    """The slice of the app's storage backend the purge uses."""

    def delete(self, bucket: str, object_path: str) -> None:
        """Remove an object; a missing one is not an error."""
        ...


@dataclass(slots=True)
class ObjectPurgeReport:
    """Outcome of the storage half; ``failed`` is what the operator must retry by hand."""

    deleted: dict[str, int] = field(default_factory=dict)
    failed: list[tuple[str, str]] = field(default_factory=list)


def purge_objects(
    storage: ObjectDeleter, buckets: Mapping[str, str], objects: Mapping[str, Iterable[str]]
) -> ObjectPurgeReport:
    """Delete each object through ``storage``. Idempotent: a missing object counts as done.

    One failure never stops the rest; it is recorded as ``bucket/key`` with the error.
    """
    report = ObjectPurgeReport()
    for kind, keys in objects.items():
        bucket = buckets[kind]
        for key in keys:
            try:
                storage.delete(bucket, key)
            except Exception as exc:
                report.failed.append((f"{bucket}/{key}", f"{type(exc).__name__}: {exc}"))
                continue
            report.deleted[kind] = report.deleted.get(kind, 0) + 1
    return report


def storage_config_problems(settings: Settings, verdict: EnvironmentVerdict) -> list[str]:
    """Why the configured storage cannot be trusted to delete this environment's objects.

    The storage backend defaults to ``local``, which would "delete" files on this machine and
    report success. So outside a local database the backend must be ``gcs`` with all three bucket
    names set explicitly, and each name must carry the environment the database check detected
    (``staging`` or ``production``), so a staging database cannot be paired with production
    buckets or the reverse. An unrecognised target (override flag) needs the explicit buckets
    but cannot be matched to a name.
    """
    if verdict.kind == "local":
        return []
    storage = settings.storage
    problems: list[str] = []
    if storage.backend != "gcs":
        problems.append(
            f"storage backend is {storage.backend!r}, not 'gcs': objects would not be deleted "
            "from the real buckets (set LEMELY_STORAGE__BACKEND=gcs)"
        )
    names = {
        "bucket": "LEMELY_STORAGE__BUCKET",
        "avatar_bucket": "LEMELY_STORAGE__AVATAR_BUCKET",
        "tutor_evidence_bucket": "LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET",
    }
    for field_name, env_var in names.items():
        if field_name not in storage.model_fields_set:
            problems.append(f"{env_var} is not set explicitly (the default is a placeholder)")
            continue
        value = str(getattr(storage, field_name))
        if verdict.kind in ("staging", "production") and verdict.kind not in value.lower():
            problems.append(
                f"{env_var}={value!r} does not name the {verdict.kind} environment the "
                "database check detected"
            )
    return problems


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Account:
    """One ``public.users`` row, as the purge reports it."""

    id: uuid.UUID
    email: str
    role: str
    created_at: datetime
    email_verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Step:
    kind: Literal["delete", "null"]
    table: str
    columns: tuple[str, ...]
    values: tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True)
class KeptImpact:
    """Rows a purged account owns that a kept account depends on (they go with the owner)."""

    table: str
    column: str
    kept_email: str
    rows: int


@dataclass(slots=True)
class PurgePlan:
    """What a purge would do, computed without writing anything."""

    keep_domains: tuple[str, ...]
    to_delete: list[Account] = field(default_factory=list)
    kept_verified: list[Account] = field(default_factory=list)
    unverified_allowlisted: list[Account] = field(default_factory=list)
    include_unverified_allowlisted: bool = False
    #: Rows that disappear, per table (the users themselves, cascades and explicit deletes).
    deleted_rows: dict[str, int] = field(default_factory=dict)
    #: Rows that survive with a reference cleared, keyed ``table.column``.
    detached_rows: dict[str, int] = field(default_factory=dict)
    #: Rows owned by purged accounts that kept accounts reference: the kept side loses them.
    kept_impacts: list[KeptImpact] = field(default_factory=list)
    steps: list[_Step] = field(default_factory=list)
    #: Object keys to delete, per logical bucket (``uploads``, ``avatars``, ``tutor_evidence``).
    objects: dict[str, list[str]] = field(default_factory=dict)
    #: Keys the doomed rows share with a surviving row, so they are kept.
    objects_kept_shared: int = 0
    #: Every key a surviving row references, per bucket: never deleted, whatever sweeps find.
    protected_keys: dict[str, set[str]] = field(default_factory=dict)
    #: Per-user key prefixes to list for objects no row references, per bucket.
    prefixes: dict[str, list[str]] = field(default_factory=dict)
    #: Keys found under those prefixes that no row references (added to :attr:`objects`).
    unreferenced_objects: int = 0

    @property
    def delete_ids(self) -> list[uuid.UUID]:
        """Ids of every account the purge removes."""
        return [account.id for account in self.to_delete]


@dataclass(frozen=True, slots=True)
class _Ref:
    child_table: str
    child_columns: tuple[str, ...]
    parent_columns: tuple[str, ...]
    on_delete: str  # pg_constraint.confdeltype: a, r, c, n, d
    all_nullable: bool


# Column lists come back in constraint order, so a composite key lines up child to parent.
_REFS_SQL = sa.text(
    """
    SELECT cl.relname AS child_table, con.confdeltype AS on_delete,
      ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
            ORDER BY k.ord) AS child_columns,
      ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
            ORDER BY k.ord) AS parent_columns,
      (SELECT bool_and(NOT a.attnotnull) FROM unnest(con.conkey) k(attnum)
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
      ) AS all_nullable
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_class pcl ON pcl.oid = con.confrelid
    WHERE con.contype = 'f'
      AND pcl.relname = :parent
      AND pcl.relnamespace = 'public'::regnamespace
      AND cl.relnamespace = 'public'::regnamespace
    ORDER BY cl.relname, con.conname
    """
)

_CTID: sa.ColumnClause[str] = sa.literal_column("ctid::text", type_=sa.String())


def _tbl(name: str, columns: Iterable[str]) -> sa.TableClause:
    return sa.table(name, *[sa.column(c) for c in columns])


def _match(
    table: sa.TableClause, columns: tuple[str, ...], values: Iterable[tuple[object, ...]]
) -> sa.ColumnElement[bool]:
    """``(c1, c2) IN (...)``: every key column of a (possibly composite) foreign key."""
    return sa.tuple_(*[table.c[c] for c in columns]).in_(list(values))


class _Walker:
    """Walks the foreign-key graph from ``users`` and records every effect.

    Keys are tuples, one value per key column, so a composite foreign key is matched on every
    column and a single-column one is just a one-tuple.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._refs: dict[str, list[_Ref]] = {}
        self._doomed: dict[str, set[str]] = defaultdict(set)
        self.detached: dict[str, int] = defaultdict(int)
        self.steps: list[_Step] = []

    def refs_to(self, table: str) -> list[_Ref]:
        if table not in self._refs:
            self._refs[table] = [
                _Ref(
                    child_table=row["child_table"],
                    child_columns=tuple(row["child_columns"]),
                    parent_columns=tuple(row["parent_columns"]),
                    on_delete=row["on_delete"],
                    all_nullable=bool(row["all_nullable"]),
                )
                for row in self._conn.execute(_REFS_SQL, {"parent": table}).mappings()
            ]
        return self._refs[table]

    def _rows(self, stmt: sa.sql.Executable) -> list[tuple[object, ...]]:
        return [tuple(row) for row in self._conn.execute(stmt)]

    def collect(
        self,
        table: str,
        columns: tuple[str, ...],
        values: list[tuple[object, ...]],
        *,
        explicit: bool,
        depth: int = 0,
    ) -> None:
        """Record the rows of ``table`` whose ``columns`` match ``values`` as doomed.

        ``explicit`` rows get a delete step of their own (a ``NOT NULL`` no-action child); cascade
        children are only counted, because the database removes them with their parent.
        """
        if table in PROTECTED_TABLES:
            raise PurgeError(f"the purge would reach protected table {table}; refusing.")
        if depth > _MAX_DEPTH:
            raise PurgeError(f"foreign-key chain from users is deeper than {_MAX_DEPTH} at {table}")
        if not values:
            return
        refs = self.refs_to(table)
        needed = sorted({c for ref in refs for c in ref.parent_columns} | set(columns))
        tbl = _tbl(table, needed)
        found = self._rows(sa.select(_CTID).select_from(tbl).where(_match(tbl, columns, values)))
        new = [str(row[0]) for row in found if str(row[0]) not in self._doomed[table]]
        if not new:
            return
        self._doomed[table].update(new)
        for ref in refs:
            keys = [
                row
                for row in self._rows(
                    sa.select(*[tbl.c[c] for c in ref.parent_columns])
                    .distinct()
                    .select_from(tbl)
                    .where(_CTID.in_(new))
                )
                if all(v is not None for v in row)
            ]
            if not keys:
                continue
            child = _tbl(ref.child_table, ref.child_columns)
            if ref.on_delete == "c":
                self.collect(
                    ref.child_table, ref.child_columns, keys, explicit=False, depth=depth + 1
                )
                continue
            count = self._conn.execute(
                sa.select(sa.func.count())
                .select_from(child)
                .where(_match(child, ref.child_columns, keys))
            ).scalar_one()
            label = f"{ref.child_table}.{'+'.join(ref.child_columns)}"
            if ref.on_delete in ("n", "d"):
                if count:
                    self.detached[label] += count
            elif ref.all_nullable:
                if count:
                    self.detached[label] += count
                    self.steps.append(
                        _Step("null", ref.child_table, ref.child_columns, tuple(keys))
                    )
            else:
                self.collect(
                    ref.child_table, ref.child_columns, keys, explicit=True, depth=depth + 1
                )
        if explicit:
            self.steps.append(_Step("delete", table, columns, tuple(values)))

    def doomed_ctids(self) -> dict[str, set[str]]:
        return self._doomed

    def deleted_counts(self) -> dict[str, int]:
        return {t: len(c) for t, c in sorted(self._doomed.items()) if c}

    def kept_impacts(self, kept: dict[uuid.UUID, str]) -> list[KeptImpact]:
        """Doomed non-user rows that point at a *kept* account, grouped by table and column."""
        impacts: list[KeptImpact] = []
        for ref in self.refs_to("users"):
            ctids = self._doomed.get(ref.child_table)
            if not ctids or ref.child_table == "users" or len(ref.child_columns) != 1:
                continue
            col = ref.child_columns[0]
            tbl = _tbl(ref.child_table, [col])
            rows = self._conn.execute(
                sa.select(tbl.c[col], sa.func.count())
                .where(_CTID.in_(sorted(ctids)), tbl.c[col].is_not(None))
                .group_by(tbl.c[col])
            )
            impacts.extend(
                KeptImpact(ref.child_table, col, kept[uid], n) for uid, n in rows if uid in kept
            )
        return sorted(impacts, key=lambda i: (i.table, i.column, i.kept_email))


def check_schema_at_head(conn: Connection) -> str:
    """Return the revision, or raise :class:`PurgeError` unless the database is at Alembic head.

    The purge walks the live foreign keys, so it must run on the schema this code expects: after
    the release's migrations, never before. A database with no ``alembic_version`` row, behind
    head, or ahead of this code is refused with the exact revisions.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    import lemely.db as db_package

    config = Config()
    config.set_main_option("script_location", str(Path(db_package.__file__).parent / "migrations"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    try:
        rows = {r[0] for r in conn.execute(sa.text("SELECT version_num FROM alembic_version"))}
    except sa.exc.ProgrammingError as exc:
        raise PurgeError(
            "This database has no alembic_version table: it was never migrated. Refusing."
        ) from exc
    if rows != heads:
        raise PurgeError(
            f"Database schema is at revision {', '.join(sorted(rows)) or '(none)'} but this "
            f"code expects head {', '.join(sorted(heads))}. Run the release deploy's migrations "
            "first, then re-run the purge. Refusing."
        )
    return ", ".join(sorted(rows))


def _accounts(conn: Connection) -> list[Account]:
    rows = conn.execute(
        sa.text(
            "SELECT id, email, role::text AS role, created_at, email_verified_at "
            "FROM users ORDER BY created_at, email"
        )
    ).mappings()
    return [
        Account(
            id=row["id"],
            email=row["email"],
            role=row["role"],
            created_at=row["created_at"],
            email_verified_at=row["email_verified_at"],
        )
        for row in rows
    ]


def plan_purge(
    conn: Connection,
    keep_domains: Iterable[str],
    *,
    include_unverified_allowlisted: bool = False,
) -> PurgePlan:
    """Compute the purge without writing: who goes, what is kept, and the row counts.

    Raises:
        PurgeError: ``keep_domains`` is empty (nothing would be kept), or the schema has a shape
            the walker does not handle.
    """
    domains = tuple(d for d in keep_domains if d)
    if not domains:
        raise PurgeError("At least one keep domain is required; refusing to delete every account.")
    plan = PurgePlan(
        keep_domains=domains, include_unverified_allowlisted=include_unverified_allowlisted
    )
    for account in _accounts(conn):
        if not is_allowed_email(account.email, domains):
            plan.to_delete.append(account)
        elif account.email_verified_at is None:
            plan.unverified_allowlisted.append(account)
            if include_unverified_allowlisted:
                plan.to_delete.append(account)
        else:
            plan.kept_verified.append(account)
    if plan.to_delete:
        walker = _Walker(conn)
        walker.collect("users", ("id",), [(i,) for i in plan.delete_ids], explicit=True)
        plan.deleted_rows = walker.deleted_counts()
        plan.detached_rows = dict(sorted(walker.detached.items()))
        plan.steps = walker.steps
        kept = {a.id: a.email for a in plan.kept_verified + plan.unverified_allowlisted}
        for account in plan.to_delete:
            kept.pop(account.id, None)
        plan.kept_impacts = walker.kept_impacts(kept)
        plan.objects, plan.objects_kept_shared, plan.protected_keys = collect_objects(
            conn, walker.doomed_ctids()
        )
        plan.prefixes = _prefixes(conn, plan.delete_ids, walker.doomed_ctids())
    return plan


def execute_purge(conn: Connection, plan: PurgePlan) -> dict[str, int]:
    """Run ``plan``'s steps on ``conn``, children first, and return rows removed per step table.

    The caller owns the transaction: every statement here runs inside it, so any error leaves
    the database untouched once the caller rolls back.
    """
    removed: dict[str, int] = defaultdict(int)
    for step in plan.steps:
        tbl = _tbl(step.table, step.columns)
        where = _match(tbl, step.columns, step.values)
        if step.kind == "delete":
            removed[step.table] += conn.execute(sa.delete(tbl).where(where)).rowcount
        else:
            conn.execute(sa.update(tbl).where(where).values(dict.fromkeys(step.columns)))
    return dict(removed)


# ---------------------------------------------------------------------------
# GoTrue (Supabase Auth)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AuthPurgeReport:
    """Outcome of the GoTrue half; ``failed`` is what the operator must retry."""

    deleted: list[str] = field(default_factory=list)
    already_gone: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def auth_targets(
    admin: GoTrueAdmin,
    *,
    delete_ids: Iterable[uuid.UUID],
    remaining_ids: set[uuid.UUID],
    keep_domains: Iterable[str],
    include_unverified_allowlisted: bool = False,
) -> list[tuple[uuid.UUID, str]]:
    """GoTrue users the purge should remove: the purged ids, plus orphans.

    An orphan is a GoTrue user with no ``public.users`` row and an email outside the keep-domains,
    which is exactly what a purge that deleted the row but failed on GoTrue leaves behind. Listing
    them is what makes a re-run finish the job. An orphan on a keep-domain is left alone, unless
    ``include_unverified_allowlisted`` is set: that run also deleted keep-domain accounts, and a
    failed GoTrue deletion for one of them must be retried (verification lives in the row, so a
    row-less keep-domain user is unverified by definition).
    """
    doomed = set(delete_ids)
    targets: dict[uuid.UUID, str] = {}
    for user in admin.list_users():
        if user.id in doomed or (
            user.id not in remaining_ids
            and (include_unverified_allowlisted or not is_allowed_email(user.email, keep_domains))
        ):
            targets[user.id] = user.email
    for user_id in doomed:
        targets.setdefault(user_id, "")
    return sorted(targets.items(), key=lambda item: str(item[0]))


def purge_auth_users(
    admin: GoTrueAdmin, targets: Iterable[tuple[uuid.UUID, str]]
) -> AuthPurgeReport:
    """Delete each target from GoTrue. Idempotent: a user already gone counts as done.

    Never raises for a single user: a failure is recorded and the loop continues, so one bad
    account does not strand the rest.
    """
    report = AuthPurgeReport()
    for user_id, email in targets:
        label = f"{user_id} {email}".strip()
        try:
            existed = admin.delete_user(user_id)
        except Exception as exc:
            report.failed.append((label, f"{type(exc).__name__}: {exc}"))
            continue
        (report.deleted if existed else report.already_gone).append(label)
    return report


__all__ = [
    "NON_FK_UUID_COLUMNS",
    "PRODUCTION_PROJECT_REFS",
    "PROTECTED_TABLES",
    "STAGING_PROJECT_REFS",
    "STORAGE_COLUMNS",
    "Account",
    "AuthPurgeReport",
    "EnvironmentVerdict",
    "KeptImpact",
    "ObjectDeleter",
    "ObjectLister",
    "ObjectPurgeReport",
    "PurgeError",
    "PurgePlan",
    "StorageColumn",
    "auth_targets",
    "check_schema_at_head",
    "classify_environment",
    "collect_objects",
    "discover_unreferenced",
    "execute_purge",
    "plan_purge",
    "purge_auth_users",
    "purge_objects",
    "storage_config_problems",
]
