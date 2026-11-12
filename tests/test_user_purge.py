"""``lemely admin purge-users``: the staging purge, against a throwaway migrated database.

Every database test runs on ``migrated_sessionmaker`` (a fresh database at ``alembic upgrade
head``), so the foreign-key graph the purge walks is the real one. Nothing here touches a real
staging or production database or a real Supabase project: GoTrue is an in-memory fake, and the
production-refusal tests assert the purge never even asks for an engine.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click
import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from lemely.app import purge_cli
from lemely.app.cli import cli
from lemely.auth.gotrue import GoTrueUser
from lemely.db.models import ClassEnrollment, Invite, Notification, SchoolClass, User
from lemely.db.models.enums import InviteRole, NotificationType, Role
from lemely.db.session import dispose_engine
from lemely.db.user_purge import (
    NON_FK_UUID_COLUMNS,
    STORAGE_COLUMNS,
    PurgeError,
    classify_environment,
    execute_purge,
    plan_purge,
)
from lemely.runtime.config import Settings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker

KEEP = ("lemelyig.com",)
NOW = datetime.now(UTC)
PROD_REF = "ynrmqjiqcvmcakondjbp"
STAGING_REF = "respcqftujbbyvsbkibk"


def _settings(**sections: dict[str, object]) -> Settings:
    return Settings.model_validate(sections)


# ── Environment classification (pure, no database) ───────────────────────────


def test_a_local_default_target_is_local_and_safe() -> None:
    verdict = classify_environment(Settings())
    assert verdict.kind == "local"
    assert verdict.safe


@pytest.mark.parametrize(
    "database_url",
    [
        f"postgresql+psycopg://postgres.{PROD_REF}:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
        f"postgresql+psycopg://postgres:pw@db.{PROD_REF}.supabase.co:5432/postgres",
    ],
)
def test_a_production_database_url_is_refused(database_url: str) -> None:
    verdict = classify_environment(_settings(database={"url": database_url}))
    assert verdict.kind == "production"
    assert not verdict.safe


def test_a_production_supabase_url_is_refused_even_with_a_local_database() -> None:
    verdict = classify_environment(_settings(supabase={"url": f"https://{PROD_REF}.supabase.co"}))
    assert verdict.kind == "production"


def test_a_production_bucket_or_cloud_run_service_is_refused() -> None:
    # A production-named bucket or service on a database that does not name production is a mixed
    # target: refused, but as unrecognised, so the production flag cannot pass it.
    bucket = classify_environment(_settings(storage={"bucket": "proj-uploads-production"}))
    assert bucket.kind == "unknown" and not bucket.safe
    service = classify_environment(Settings(), {"K_SERVICE": "lemely-backend-production"})
    assert service.kind == "unknown" and not service.safe
    both = classify_environment(
        _settings(database={"url": PROD_URL}, storage={"bucket": "proj-uploads-production"})
    )
    assert both.kind == "production"


def test_production_wins_over_a_staging_marker() -> None:
    verdict = classify_environment(
        _settings(
            database={"url": f"postgresql+psycopg://postgres.{STAGING_REF}:pw@pooler.example/db"},
            supabase={"url": f"https://{PROD_REF}.supabase.co"},
        )
    )
    assert verdict.kind == "production"


def test_the_staging_project_is_safe() -> None:
    verdict = classify_environment(
        _settings(
            database={"url": f"postgresql+psycopg://postgres.{STAGING_REF}:pw@pooler.example/db"},
            supabase={"url": f"https://{STAGING_REF}.supabase.co"},
        )
    )
    assert verdict.kind == "staging"
    assert verdict.safe


def test_an_unrecognised_remote_database_fails_closed() -> None:
    verdict = classify_environment(
        _settings(database={"url": "postgresql+psycopg://u:p@db.somewhere-else.example:5432/x"})
    )
    assert verdict.kind == "unknown"
    assert not verdict.safe


def test_a_staging_database_with_a_foreign_supabase_project_fails_closed() -> None:
    verdict = classify_environment(
        _settings(
            database={"url": f"postgresql+psycopg://postgres.{STAGING_REF}:pw@pooler.example/db"},
            supabase={"url": "https://someotherref.supabase.co"},
        )
    )
    assert not verdict.safe


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine(migrated_sessionmaker: sessionmaker[Session]) -> Engine:
    bind = migrated_sessionmaker.kw["bind"]
    assert isinstance(bind, sa.engine.Engine)
    return bind


def _user(
    session: Session,
    email: str,
    *,
    role: Role = Role.student,
    verified: bool = True,
) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=email,
            role=role,
            email_verified_at=NOW if verified else None,
        )
    )
    session.flush()
    return uid


class World:
    """A small population: allowed and disallowed accounts with data on both sides."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        with sm.begin() as session:
            self.keep_student = _user(session, "dev@lemelyig.com")
            self.keep_teacher = _user(session, "teach@lemelyig.com", role=Role.teacher)
            self.unverified = _user(session, "squat@lemelyig.com", verified=False)
            self.stranger = _user(session, "stranger@example.com")
            self.stranger_teacher = _user(session, "t@example.com", role=Role.teacher)
            self.lookalike = _user(session, "x@lemelyig.com.evil.com")
            self.sub = _user(session, "x@sub.lemelyig.com")
            self.phone_parent = _user(session, "phone+201@parents.lemely.local", role=Role.parent)

            # Cascade data on both sides.
            for uid in (self.keep_student, self.stranger):
                session.add(
                    Notification(user_id=uid, type=NotificationType.announcement, title="hi")
                )
            # A deleted teacher's class (NO ACTION, NOT NULL) with a KEPT student enrolled.
            doomed_class = SchoolClass(teacher_id=self.stranger_teacher, name="Doomed")
            kept_class = SchoolClass(teacher_id=self.keep_teacher, name="Kept")
            session.add_all([doomed_class, kept_class])
            session.flush()
            session.add_all(
                [
                    ClassEnrollment(class_id=doomed_class.id, student_id=self.keep_student),
                    ClassEnrollment(class_id=kept_class.id, student_id=self.stranger),
                    ClassEnrollment(class_id=kept_class.id, student_id=self.keep_student),
                ]
            )
            # An invite a deleted teacher created (NO ACTION, NOT NULL), and one a kept teacher
            # created that a deleted student redeemed (SET NULL: the invite must survive).
            session.add(
                Invite(
                    code="DOOMED01",
                    role=InviteRole.student,
                    class_id=doomed_class.id,
                    created_by=self.stranger_teacher,
                )
            )
            session.add(
                Invite(
                    code="KEPT0001",
                    role=InviteRole.student,
                    class_id=kept_class.id,
                    created_by=self.keep_teacher,
                    redeemed_by=self.stranger,
                    redeemed_at=NOW,
                )
            )
        self.disallowed = {
            self.stranger,
            self.stranger_teacher,
            self.lookalike,
            self.sub,
            self.phone_parent,
        }
        self.kept = {self.keep_student, self.keep_teacher}


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


def _ids(engine: Engine) -> set[uuid.UUID]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(sa.text("SELECT id FROM users"))}


@pytest.fixture
def world(migrated_sessionmaker: sessionmaker[Session]) -> World:
    return World(migrated_sessionmaker)


# ── Dry run ──────────────────────────────────────────────────────────────────


def test_plan_lists_the_doomed_and_the_kept_and_deletes_nothing(
    engine: Engine, world: World
) -> None:
    before = {t: _count(engine, t) for t in ("users", "notifications", "classes", "invites")}
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)

    assert {a.id for a in plan.to_delete} == world.disallowed
    assert {a.id for a in plan.kept_verified} == world.kept
    assert [a.id for a in plan.unverified_allowlisted] == [world.unverified]
    for account in plan.to_delete:
        assert account.email and account.role and account.created_at
    # The counts say what execute will do ...
    assert plan.deleted_rows["users"] == 5
    assert plan.deleted_rows["notifications"] == 1
    assert plan.deleted_rows["classes"] == 1  # the deleted teacher's class, not the kept one
    assert plan.deleted_rows["class_enrollments"] == 2  # both rows of the doomed class
    assert plan.deleted_rows["invites"] == 1
    assert plan.detached_rows["invites.redeemed_by"] == 1
    # ... and the plan itself wrote nothing.
    assert {t: _count(engine, t) for t in before} == before


def test_the_dry_run_plan_equals_what_execute_removes(engine: Engine, world: World) -> None:
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
    before = {t: _count(engine, t) for t in plan.deleted_rows}
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    after = {t: _count(engine, t) for t in plan.deleted_rows}
    assert {t: before[t] - after[t] for t in before} == plan.deleted_rows


# ── Execute ──────────────────────────────────────────────────────────────────


def test_execute_removes_only_disallowed_users_and_their_data(engine: Engine, world: World) -> None:
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))

    remaining = _ids(engine)
    assert remaining == world.kept | {world.unverified}, "only the allow-listed accounts remain"
    with engine.connect() as conn:
        # The deleted accounts' own data is gone.
        assert (
            conn.execute(sa.text("SELECT count(*) FROM invites WHERE code='DOOMED01'")).scalar_one()
            == 0
        )
        assert (
            conn.execute(sa.text("SELECT count(*) FROM classes WHERE name='Doomed'")).scalar_one()
            == 0
        )
        # The kept accounts' data survives, including the kept student's other enrolment.
        assert (
            conn.execute(sa.text("SELECT count(*) FROM classes WHERE name='Kept'")).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM class_enrollments WHERE student_id = :s"),
                {"s": world.keep_student},
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM notifications WHERE user_id = :s"),
                {"s": world.keep_student},
            ).scalar_one()
            == 1
        )
        # A kept teacher's invite survives; only its pointer to the deleted redeemer is cleared.
        row = conn.execute(
            sa.text("SELECT redeemed_by, created_by FROM invites WHERE code='KEPT0001'")
        ).one()
        assert row.redeemed_by is None
        assert row.created_by == world.keep_teacher


def test_execute_is_idempotent(engine: Engine, world: World) -> None:
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    with engine.begin() as conn:
        again = plan_purge(conn, KEEP)
        assert again.to_delete == []
        assert execute_purge(conn, again) == {}
    assert _ids(engine) == world.kept | {world.unverified}


def test_unverified_allowlisted_is_deleted_only_when_asked(engine: Engine, world: World) -> None:
    with engine.begin() as conn:
        default_plan = plan_purge(conn, KEEP)
        flagged = plan_purge(conn, KEEP, include_unverified_allowlisted=True)
    assert world.unverified not in {a.id for a in default_plan.to_delete}
    assert world.unverified in {a.id for a in flagged.to_delete}
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP, include_unverified_allowlisted=True))
    assert _ids(engine) == world.kept


def test_an_allowlisted_verified_account_is_never_deleted(engine: Engine, world: World) -> None:
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP, include_unverified_allowlisted=True)
    assert world.keep_student not in plan.delete_ids
    assert world.keep_teacher not in plan.delete_ids


def test_no_keep_domain_is_refused_rather_than_deleting_everyone(
    engine: Engine, world: World
) -> None:
    with engine.begin() as conn, pytest.raises(PurgeError, match="keep domain"):
        plan_purge(conn, ())
    assert _ids(engine) == world.disallowed | world.kept | {world.unverified}


def test_a_failure_mid_purge_rolls_everything_back(engine: Engine, world: World) -> None:
    everyone = _ids(engine)
    with pytest.raises(RuntimeError, match="boom"), engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
        raise RuntimeError("boom")
    assert _ids(engine) == everyone
    assert _count(engine, "classes") == 2


def test_nullable_no_action_pointers_are_cleared_and_chains_are_deleted(
    engine: Engine, world: World
) -> None:
    """The graph walk is generic: a table added later is handled without editing the purge.

    Synthetic tables stand in for one: an audit pointer (nullable, NO ACTION), an owned row
    (NOT NULL, NO ACTION) with a NO ACTION child and a CASCADE grandchild, and a SET NULL link.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE zz_audit (id uuid PRIMARY KEY, resolved_by uuid REFERENCES users(id));
                CREATE TABLE zz_owned (
                    id uuid PRIMARY KEY, owner uuid NOT NULL REFERENCES users(id));
                CREATE TABLE zz_child (
                    id uuid PRIMARY KEY, owned uuid NOT NULL REFERENCES zz_owned(id));
                CREATE TABLE zz_grandchild (
                    id uuid PRIMARY KEY,
                    child uuid NOT NULL REFERENCES zz_child(id) ON DELETE CASCADE);
                CREATE TABLE zz_link (
                    id uuid PRIMARY KEY, who uuid REFERENCES users(id) ON DELETE SET NULL);
                """
            )
        )
        audit, owned, child, grand, link = (uuid.uuid4() for _ in range(5))
        conn.execute(
            sa.text("INSERT INTO zz_audit VALUES (:i, :u)"), {"i": audit, "u": world.stranger}
        )
        conn.execute(
            sa.text("INSERT INTO zz_owned VALUES (:i, :u)"), {"i": owned, "u": world.stranger}
        )
        conn.execute(sa.text("INSERT INTO zz_child VALUES (:i, :o)"), {"i": child, "o": owned})
        conn.execute(sa.text("INSERT INTO zz_grandchild VALUES (:i, :c)"), {"i": grand, "c": child})
        conn.execute(
            sa.text("INSERT INTO zz_link VALUES (:i, :u)"), {"i": link, "u": world.stranger}
        )

    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
        assert plan.deleted_rows["zz_owned"] == 1
        assert plan.deleted_rows["zz_child"] == 1
        assert plan.deleted_rows["zz_grandchild"] == 1
        assert plan.detached_rows["zz_audit.resolved_by"] == 1
        assert plan.detached_rows["zz_link.who"] == 1
        execute_purge(conn, plan)

    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT resolved_by FROM zz_audit")).scalar_one() is None
        assert conn.execute(sa.text("SELECT who FROM zz_link")).scalar_one() is None
        for table in ("zz_owned", "zz_child", "zz_grandchild"):
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608
    assert world.stranger not in _ids(engine)


# ── The command: safety rails and the Supabase Auth step ─────────────────────


class FakeAdmin:
    """In-memory GoTrue admin: a list of users, with optional per-user failures."""

    def __init__(self, users: list[GoTrueUser], *, fail: set[uuid.UUID] | None = None) -> None:
        self.users = {u.id: u for u in users}
        self.fail = fail or set()
        self.delete_calls: list[uuid.UUID] = []

    def list_users(self) -> list[GoTrueUser]:
        return list(self.users.values())

    def delete_user(self, user_id: uuid.UUID) -> bool:
        self.delete_calls.append(user_id)
        if user_id in self.fail:
            raise RuntimeError("503 from GoTrue")
        return self.users.pop(user_id, None) is not None


@pytest.fixture
def local_settings(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Settings pointing at the throwaway database (a local host, so the purge allows it)."""
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("LEMELY_DATABASE__URL", url)
    dispose_engine()
    try:
        yield Settings()
    finally:
        dispose_engine()


def _run(
    settings: Settings,
    admin: FakeAdmin,
    *,
    execute: bool,
    storage: FakeStorage | None = None,
    **flags: bool,
) -> int:
    return purge_cli.purge_users_command(
        settings,
        keep_domains=KEEP,
        execute=execute,
        include_unverified_allowlisted=flags.get("include_unverified_allowlisted", False),
        allow_production=flags.get("allow_production", False),
        json_output=flags.get("json_output", False),
        admin=admin,
        storage=storage,
    )


def _gotrue_users(engine: Engine) -> list[GoTrueUser]:
    with engine.connect() as conn:
        return [
            GoTrueUser(id=r.id, email=r.email)
            for r in conn.execute(sa.text("SELECT id, email FROM users"))
        ]


def test_dry_run_prints_and_deletes_nothing(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    before = _ids(engine)
    assert _run(local_settings, admin, execute=False) == 0

    out = capsys.readouterr().out
    assert _ids(engine) == before
    assert admin.delete_calls == []
    assert "Dry run: nothing was deleted" in out
    assert "stranger@example.com" in out  # id, email, role, created_at are listed
    assert "UNVERIFIED accounts (kept): 1" in out
    assert "squat@lemelyig.com" in out
    # A kept account appears only in the "affected" section, never in the delete list.
    assert "dev@lemelyig.com: 1 row(s) in class_enrollments.student_id" in out
    assert "dev@lemelyig.com" not in out.split("=== ACCOUNTS TO DELETE")[1]
    assert out.index("KEPT ACCOUNTS WHOSE DATA IS AFFECTED") < out.index("=== ACCOUNTS TO DELETE")
    assert "notifications: 1" in out  # per-table dependent counts


def test_execute_deletes_db_rows_then_auth_users(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    assert _run(local_settings, admin, execute=True) == 0
    assert _ids(engine) == world.kept | {world.unverified}
    assert set(admin.delete_calls) == world.disallowed
    assert set(admin.users) == world.kept | {world.unverified}


def test_a_failed_auth_deletion_is_reported_and_a_rerun_finishes_the_job(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine), fail={world.stranger})
    assert _run(local_settings, admin, execute=True) == 1
    err = capsys.readouterr().err
    assert "FAILED" in err and "stranger@example.com" in err
    assert _ids(engine) == world.kept | {world.unverified}, "the database half still committed"
    assert world.stranger in admin.users, "the failed Auth user is still there"

    # The row is gone from the database now, so only the orphan sweep can find it: a re-run
    # (GoTrue healthy again) deletes it and reports success.
    admin.fail.clear()
    assert _run(local_settings, admin, execute=True) == 0
    assert world.stranger not in admin.users
    assert set(admin.users) == world.kept | {world.unverified}


def test_the_orphan_sweep_never_touches_an_allowlisted_or_kept_user(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    allowed_orphan = GoTrueUser(id=uuid.uuid4(), email="mid-signup@lemelyig.com")
    foreign_orphan = GoTrueUser(id=uuid.uuid4(), email="gone@example.com")
    admin = FakeAdmin([*_gotrue_users(engine), allowed_orphan, foreign_orphan])
    assert _run(local_settings, admin, execute=True) == 0
    assert allowed_orphan.id in admin.users, "an allow-listed GoTrue user must survive"
    assert foreign_orphan.id not in admin.users


def test_a_user_already_gone_from_auth_is_success(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    admin = FakeAdmin([u for u in _gotrue_users(engine) if u.id != world.stranger])
    assert _run(local_settings, admin, execute=True) == 0


def test_include_unverified_flag_reaches_the_command(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    assert _run(local_settings, admin, execute=True, include_unverified_allowlisted=True) == 0
    assert _ids(engine) == world.kept
    assert world.unverified in set(admin.delete_calls)


class _NoConnect:
    """Stands in for ``get_engine`` where reaching it would already be the bug."""

    def __call__(self, *_: object, **__: object) -> object:
        raise AssertionError("the purge asked for a database engine on a refused target")


@pytest.mark.parametrize(
    "database_url",
    [
        f"postgresql+psycopg://postgres.{PROD_REF}:pw@aws-0-eu.pooler.supabase.com:6543/postgres",
        "postgresql+psycopg://u:p@db.unknown-host.example:5432/postgres",
    ],
)
def test_production_and_unknown_targets_are_refused_before_connecting(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    settings = _settings(database={"url": database_url})
    for execute in (False, True):
        with pytest.raises(click.ClickException, match="Refusing to purge"):
            _run(settings, FakeAdmin([]), execute=execute)


def test_the_production_flag_is_the_only_way_past_the_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the awkward flag the purge gets as far as asking for the engine (and we stop there)."""
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    settings = _settings(
        database={
            "url": f"postgresql+psycopg://postgres.{PROD_REF}:pw@pooler.example:6543/postgres"
        }
    )
    with pytest.raises(AssertionError, match="asked for a database engine"):
        _run(settings, FakeAdmin([]), execute=False, allow_production=True)
    assert "continuing" in capsys.readouterr().err


def test_execute_without_a_service_role_key_changes_nothing(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    before = _ids(engine)
    with pytest.raises(click.ClickException, match="service-role key"):
        purge_cli.purge_users_command(
            local_settings,
            keep_domains=KEEP,
            execute=True,
            include_unverified_allowlisted=False,
            allow_production=False,
            json_output=False,
        )
    assert _ids(engine) == before


def test_no_keep_domain_and_no_access_setting_is_a_usage_error(local_settings: Settings) -> None:
    with pytest.raises(click.UsageError, match="No keep domain"):
        purge_cli.purge_users_command(
            local_settings,
            keep_domains=(),
            execute=False,
            include_unverified_allowlisted=False,
            allow_production=False,
            json_output=False,
        )


def test_keep_domain_defaults_to_the_access_setting(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch, local_settings: Settings
) -> None:
    monkeypatch.setenv("LEMELY_ACCESS__ALLOWED_EMAIL_DOMAINS", "lemelyig.com")
    settings = Settings()
    admin = FakeAdmin(_gotrue_users(engine))
    code = purge_cli.purge_users_command(
        settings,
        keep_domains=(),
        execute=False,
        include_unverified_allowlisted=False,
        allow_production=False,
        json_output=False,
        admin=admin,
    )
    assert code == 0


def test_the_cli_is_wired_and_defaults_to_a_dry_run(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    before = _ids(engine)
    result = CliRunner().invoke(cli, ["admin", "purge-users", "--keep-domain", "lemelyig.com"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing was deleted" in result.output
    assert _ids(engine) == before


def test_the_cli_refuses_execute_on_a_production_looking_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LEMELY_DATABASE__URL",
        f"postgresql+psycopg://postgres.{PROD_REF}:pw@aws-0-eu.pooler.supabase.com:6543/postgres",
    )
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    result = CliRunner().invoke(
        cli, ["admin", "purge-users", "--keep-domain", "lemelyig.com", "--execute"]
    )
    assert result.exit_code != 0
    assert "Refusing to purge" in result.output
    assert "--i-know-this-is-production" in result.output


# ── Schema at head, waitlist untouched, summary first ────────────────────────


def _alembic_head() -> str:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    import lemely.db as db_package

    config = Config()
    config.set_main_option("script_location", str(Path(db_package.__file__).parent / "migrations"))
    (head,) = ScriptDirectory.from_config(config).get_heads()
    return head


def _set_revision(engine: Engine, revision: str) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE alembic_version SET version_num = :r"), {"r": revision})


def test_a_database_behind_head_is_refused_even_for_a_dry_run(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    _set_revision(engine, "0023_invites")
    before = _ids(engine)
    for execute in (False, True):
        with pytest.raises(click.ClickException, match=f"expects head {_alembic_head()}"):
            _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=execute)
    assert _ids(engine) == before


def test_a_database_with_no_alembic_version_is_refused(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE alembic_version"))
    with pytest.raises(click.ClickException, match="never migrated"):
        _run(local_settings, FakeAdmin([]), execute=False)


def test_waitlist_applicants_are_never_touched(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO waitlist_applicants (email, role, consent_version, consent_text, "
                "consent_at) VALUES ('stranger@example.com', 'student', 'v', 't', now())"
            )
        )
    assert _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=True) == 0
    assert _count(engine, "waitlist_applicants") == 1
    assert world.stranger not in _ids(engine)


def test_the_walk_stops_if_a_protected_table_ever_references_users(
    engine: Engine, world: World
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "ALTER TABLE waitlist_applicants ADD COLUMN who uuid REFERENCES users(id) "
                "ON DELETE CASCADE"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO waitlist_applicants (email, role, consent_version, consent_text, "
                "consent_at, who) VALUES ('w@example.com', 'student', 'v', 't', now(), :u)"
            ),
            {"u": world.stranger},
        )
    with engine.begin() as conn, pytest.raises(PurgeError, match="protected table"):
        plan_purge(conn, KEEP)
    assert _count(engine, "waitlist_applicants") == 1


def test_the_dry_run_leads_with_a_count_summary_then_the_list(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False)
    out = capsys.readouterr().out
    assert out.startswith("=== SUMMARY ===")
    assert out.index("Accounts to delete: 5") < out.index("stranger@example.com")
    assert "Waitlist applicants: never touched." in out


# ── Storage objects ──────────────────────────────────────────────────────────


class FakeStorage:
    """Records deletes as ``(bucket, key)``; ``fail`` keys raise. ``on_delete`` sees every call."""

    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.fail = fail or set()
        self.on_delete: list[Callable[[], None]] = []

    def delete(self, bucket: str, object_path: str) -> None:
        for hook in self.on_delete:
            hook()
        if object_path in self.fail:
            raise RuntimeError("503 from storage")
        self.deleted.append((bucket, object_path))


UP, AV, EV = "lemely-uploads", "lemely-avatars", "lemely-tutor-evidence"


def _insert_objects(engine: Engine, world: World) -> None:
    def run(conn: sa.Connection, sql: str, **bind: object) -> None:
        conn.execute(sa.text(sql), bind)

    with engine.begin() as conn:
        for owner, path in [
            (world.stranger, "u/stranger/a.pdf"),
            (world.stranger, "shared/x.pdf"),
            (world.keep_student, "shared/x.pdf"),  # the same key, held by a kept account too
            (world.keep_student, "u/keep/b.pdf"),
            (world.stranger, "u/mixed/p.pdf"),  # shares mark_scheme.pdf with the kept upload below
            (world.keep_student, "u/mixed/q.pdf"),
        ]:
            run(
                conn, "INSERT INTO uploads (user_id, storage_path) VALUES (:u, :p)", u=owner, p=path
            )
        run(conn, "UPDATE users SET avatar_path='av/stranger.png' WHERE id=:u", u=world.stranger)
        run(conn, "UPDATE users SET avatar_path='av/keep.png' WHERE id=:u", u=world.keep_student)
        run(
            conn,
            "INSERT INTO teacher_papers (uploaded_by, storage_path, scheme_storage_path) "
            "VALUES (:u, 'tp/doomed.pdf', 'tp/doomed_scheme.pdf')",
            u=world.stranger_teacher,
        )
        run(
            conn,
            "INSERT INTO teacher_papers (uploaded_by, storage_path) VALUES (:u, 'tp/kept.pdf')",
            u=world.keep_teacher,
        )
        for owner, key in [
            (world.stranger_teacher, "ev/doomed.pdf"),
            (world.keep_teacher, "ev/kept.pdf"),
        ]:
            pid = uuid.uuid4()
            run(
                conn,
                "INSERT INTO tutor_profiles "
                "(id, user_id, public_first_name, headline, area_code, offers_virtual) "
                "VALUES (:i, :u, 'T', 'h', 'maadi', true)",
                i=pid,
                u=owner,
            )
            run(
                conn,
                "INSERT INTO tutor_evidence_files (tutor_profile_id, storage_path, "
                "original_filename, content_type, size_bytes) "
                "VALUES (:i, :k, 'f.pdf', 'application/pdf', 10)",
                i=pid,
                k=key,
            )


DOOMED_OBJECTS = {
    "uploads": sorted(
        [
            "u/stranger/a.pdf",
            "u/stranger/mark_scheme.pdf",
            "u/mixed/p.pdf",
            "tp/doomed.pdf",
            "tp/doomed_scheme.pdf",
        ]
    ),
    "avatars": ["av/stranger.png"],
    "tutor_evidence": ["ev/doomed.pdf"],
}


@pytest.fixture
def objects_world(engine: Engine, world: World) -> World:
    _insert_objects(engine, world)
    return world


def test_the_plan_lists_only_objects_no_surviving_row_references(
    engine: Engine, objects_world: World
) -> None:
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
    assert plan.objects == DOOMED_OBJECTS
    # shared/x.pdf, plus the mark_scheme.pdf siblings of shared/ and u/mixed/, which a kept
    # upload also owns
    assert plan.objects_kept_shared == 3


def test_dry_run_reports_object_counts_and_deletes_nothing(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = FakeStorage()
    assert (
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False, storage=storage) == 0
    )
    out = capsys.readouterr().out
    assert storage.deleted == []
    assert "Storage objects to delete: 7" in out
    assert "  uploads: 5" in out and "  avatars: 1" in out and "  tutor_evidence: 1" in out
    assert "kept (shared with a surviving account): 3" in out


def test_execute_deletes_only_the_purged_users_objects_after_their_rows_commit(
    engine: Engine, objects_world: World, local_settings: Settings
) -> None:
    storage = FakeStorage()

    def _rows_already_gone() -> None:
        # The database goes first: no object is deleted until the rows are committed away, so a
        # database failure can never leave a row pointing at a deleted file.
        assert objects_world.stranger not in _ids(engine), "an object went before its rows"

    storage.on_delete.append(_rows_already_gone)
    assert (
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=True, storage=storage) == 0
    )
    got: dict[str, list[str]] = {}
    names = {UP: "uploads", AV: "avatars", EV: "tutor_evidence"}
    for bucket, key in storage.deleted:
        got.setdefault(names[bucket], []).append(key)
    assert {k: sorted(v) for k, v in got.items()} == DOOMED_OBJECTS
    survivors = {"shared/x.pdf", "u/keep/b.pdf", "u/mixed/q.pdf", "u/mixed/mark_scheme.pdf"}
    survivors |= {"av/keep.png", "tp/kept.pdf", "ev/kept.pdf"}
    assert survivors.isdisjoint({key for _, key in storage.deleted})


def test_a_storage_failure_keeps_the_auth_users_and_a_rerun_completes(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    storage = FakeStorage(fail={"av/stranger.png"})
    assert _run(local_settings, admin, execute=True, storage=storage) == 1
    err = capsys.readouterr().err
    assert "FAILED lemely-avatars/av/stranger.png" in err
    assert "database rows are already gone" in err
    assert _ids(engine) == objects_world.kept | {objects_world.unverified}
    assert admin.delete_calls == [], "Auth users went although an object could not be deleted"
    # This key is outside the per-user folders a re-run sweeps, so the CLI must name it for
    # deletion by hand rather than promise a retry.
    assert "delete these by hand" in err.lower()
    assert "lemely-avatars/av/stranger.png" in err.lower().split("by hand", 1)[1]

    # The cause is fixed: the rerun deletes the Auth users, which are still listed as orphans.
    healthy = FakeStorage()
    assert _run(local_settings, admin, execute=True, storage=healthy) == 0
    assert set(admin.delete_calls) >= objects_world.disallowed
    # The failed key's row is gone and its key sits under no orphan folder: the rerun never sees
    # it (the assertion this replaces expected a retry, which only held with the old order).
    assert ("lemely-avatars", "av/stranger.png") not in healthy.deleted


def test_every_path_like_column_in_the_schema_is_a_registered_storage_column(
    engine: Engine,
) -> None:
    with engine.connect() as conn:
        found = {
            (r.table_name, r.column_name)
            for r in conn.execute(
                sa.text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND (column_name LIKE '%path%' "
                    "OR column_name LIKE '%storage%' OR column_name LIKE '%object_key%' "
                    "OR column_name LIKE '%bucket%')"
                )
            )
        }
    registered = {(c.table, c.column) for c in STORAGE_COLUMNS}
    assert found == registered, f"unregistered object-key columns: {found - registered}"


# ── Composite foreign keys (bookings, reviews, replies) ──────────────────────


def _tutor_profile(conn: sa.Connection, owner: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO tutor_profiles "
            "(id, user_id, public_first_name, headline, area_code, offers_virtual) "
            "VALUES (:i, :u, 'T', 'h', 'maadi', true)"
        ),
        {"i": pid, "u": owner},
    )
    return pid


def _booking_chain(
    conn: sa.Connection,
    *,
    student: uuid.UUID,
    profile: uuid.UUID,
    review: bool = True,
    reply: bool = True,
) -> uuid.UUID:
    """A completed booking, plus its review and the tutor's reply (the composite-FK chain)."""
    booking = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO tutor_bookings (id, tutor_profile_id, student_id, requested_by_party, "
            "subject_code, mode, starts_at, ends_at, state, accepted_at, completed_at, "
            "completed_by_party) VALUES (:b, :p, :s, 'student', '0625', 'other', "
            "now() - interval '2 days', now() - interval '2 days' + interval '1 hour', "
            "'completed', now() - interval '3 days', now() - interval '1 day', 'tutor')"
        ),
        {"b": booking, "p": profile, "s": student},
    )
    if review:
        review_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO tutor_reviews (id, booking_id, tutor_profile_id, student_id, stars, "
                "text_state) VALUES (:r, :b, :p, :s, 5, 'none')"
            ),
            {"r": review_id, "b": booking, "p": profile, "s": student},
        )
        if reply:
            conn.execute(
                sa.text(
                    "INSERT INTO tutor_review_replies (review_id, tutor_profile_id, body) "
                    "VALUES (:r, :p, 'thanks')"
                ),
                {"r": review_id, "p": profile},
            )
    return booking


def test_bookings_reviews_and_replies_of_purged_users_are_purged_without_error(
    engine: Engine, world: World
) -> None:
    """Composite foreign keys: a review points at its booking on (id, tutor) and (id, student)."""
    with engine.begin() as conn:
        purged_tutor = _tutor_profile(conn, world.stranger_teacher)
        kept_tutor = _tutor_profile(conn, world.keep_teacher)
        # purged student with a kept tutor, purged tutor with a kept student, purged with purged
        _booking_chain(conn, student=world.stranger, profile=kept_tutor)
        _booking_chain(conn, student=world.keep_student, profile=purged_tutor)
        _booking_chain(conn, student=world.sub, profile=purged_tutor)
        # a kept student with a kept tutor must be untouched
        keep_booking = _booking_chain(conn, student=world.keep_student, profile=kept_tutor)

    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
        assert plan.deleted_rows["tutor_bookings"] == 3
        assert plan.deleted_rows["tutor_reviews"] == 3
        assert plan.deleted_rows["tutor_review_replies"] == 3
        execute_purge(conn, plan)

    with engine.connect() as conn:
        assert _ids(engine) == world.kept | {world.unverified}
        assert conn.execute(sa.text("SELECT id FROM tutor_bookings")).scalars().all() == [
            keep_booking
        ]
        assert conn.execute(sa.text("SELECT count(*) FROM tutor_reviews")).scalar_one() == 1
        assert conn.execute(sa.text("SELECT count(*) FROM tutor_review_replies")).scalar_one() == 1


def test_a_kept_students_booking_with_a_purged_tutor_is_listed_as_affected(
    engine: Engine, world: World
) -> None:
    with engine.begin() as conn:
        purged_tutor = _tutor_profile(conn, world.stranger_teacher)
        _booking_chain(conn, student=world.keep_student, profile=purged_tutor)
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
    affected = {(i.table, i.kept_email) for i in plan.kept_impacts}
    assert ("tutor_bookings", "dev@lemelyig.com") in affected
    assert ("tutor_reviews", "dev@lemelyig.com") in affected


# ── Kept accounts affected (M2) ──────────────────────────────────────────────


def test_the_plan_names_the_kept_accounts_whose_rows_go_with_a_purged_owner(
    engine: Engine, world: World
) -> None:
    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
    assert [(i.table, i.column, i.kept_email, i.rows) for i in plan.kept_impacts] == [
        ("class_enrollments", "student_id", "dev@lemelyig.com", 1)
    ]


# ── Storage configuration (S1) ───────────────────────────────────────────────

GOOD_STORAGE = {
    "backend": "gcs",
    "bucket": "proj-uploads-staging",
    "avatar_bucket": "proj-avatars-staging",
    "tutor_evidence_bucket": "proj-tutor-evidence-staging",
    "gcs_project": "proj",
    "gcs_project_number": 123,
}


def _verdict(kind: str) -> object:
    from lemely.db.user_purge import EnvironmentVerdict

    return EnvironmentVerdict(kind, ("test",), "127.0.0.1")  # type: ignore[arg-type]


def test_storage_config_problems_by_environment() -> None:
    from lemely.db.user_purge import storage_config_problems

    staging, production = _verdict("staging"), _verdict("production")
    assert storage_config_problems(Settings(), _verdict("local")) == []  # type: ignore[arg-type]
    good = _settings(storage=GOOD_STORAGE)
    assert storage_config_problems(good, staging) == []  # type: ignore[arg-type]
    default_backend = storage_config_problems(Settings(), staging)  # type: ignore[arg-type]
    assert any("not 'gcs'" in p for p in default_backend)
    assert sum("not set explicitly" in p for p in default_backend) == 3
    # staging buckets against a production database, and the reverse
    assert any("production" in p for p in storage_config_problems(good, production))  # type: ignore[arg-type]
    prod_names = dict(GOOD_STORAGE) | {
        "bucket": "proj-uploads-production",
        "avatar_bucket": "proj-avatars-production",
        "tutor_evidence_bucket": "proj-tutor-evidence-production",
    }
    assert storage_config_problems(_settings(storage=prod_names), production) == []  # type: ignore[arg-type]
    assert any(
        "staging" in p for p in storage_config_problems(_settings(storage=prod_names), staging)
    )  # type: ignore[arg-type]
    one_wrong = dict(GOOD_STORAGE) | {"avatar_bucket": "proj-avatars-production"}
    wrong = storage_config_problems(_settings(storage=one_wrong), staging)  # type: ignore[arg-type]
    assert len(wrong) == 1 and "AVATAR_BUCKET" in wrong[0]


def _as(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    monkeypatch.setattr(purge_cli, "classify_environment", lambda *_a, **_k: _verdict(kind))


def test_a_staging_target_on_the_default_local_backend_is_flagged_and_refused(
    engine: Engine,
    world: World,
    local_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _as(monkeypatch, "staging")
    before = _ids(engine)
    assert _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False) == 0
    assert "STORAGE CONFIGURATION" in capsys.readouterr().out
    with pytest.raises(click.ClickException, match="Storage is not configured safely"):
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=True)
    assert _ids(engine) == before


class ProbingStorage(FakeStorage):
    """Storage whose ``probe_bucket`` fails for the buckets in ``unreachable``."""

    def __init__(self, unreachable: set[str] | None = None) -> None:
        super().__init__()
        self.unreachable = unreachable or set()
        self.probed: list[str] = []

    def probe_bucket(self, bucket: str) -> None:
        self.probed.append(bucket)
        if bucket in self.unreachable:
            raise PermissionError("403 storage.objects.list denied")


def test_unreachable_buckets_stop_the_purge_before_any_row_is_deleted(
    engine: Engine,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    local_settings: Settings,
) -> None:
    _as(monkeypatch, "staging")
    fake = ProbingStorage(unreachable={GOOD_STORAGE["avatar_bucket"]})  # type: ignore[arg-type]
    monkeypatch.setattr(purge_cli, "_storage_backend", lambda _s: fake)
    settings = Settings.model_validate({"storage": GOOD_STORAGE})
    before = _ids(engine)
    with pytest.raises(click.ClickException, match="not reachable") as caught:
        _run(settings, FakeAdmin(_gotrue_users(engine)), execute=True)
    assert "avatars bucket" in caught.value.message
    assert _ids(engine) == before and fake.deleted == []

    fake.unreachable.clear()
    assert _run(settings, FakeAdmin(_gotrue_users(engine)), execute=True) == 0
    assert _ids(engine) == world.kept | {world.unverified}
    assert set(fake.probed) >= {
        GOOD_STORAGE["bucket"],
        GOOD_STORAGE["avatar_bucket"],
        GOOD_STORAGE["tutor_evidence_bucket"],
    }


def test_a_dry_run_also_proves_reachability(
    engine: Engine,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _as(monkeypatch, "staging")
    fake = ProbingStorage(unreachable={GOOD_STORAGE["bucket"]})  # type: ignore[arg-type]
    monkeypatch.setattr(purge_cli, "_storage_backend", lambda _s: fake)
    settings = Settings.model_validate({"storage": GOOD_STORAGE})
    assert _run(settings, FakeAdmin(_gotrue_users(engine)), execute=False) == 0
    out = capsys.readouterr().out
    assert "uploads bucket" in out and "not reachable" in out
    assert "--execute would refuse to run" in out
    assert fake.probed, "the dry run never probed a bucket"


# ── Path-like columns (S3) ───────────────────────────────────────────────────

#: Columns whose name looks like an object key but which hold something else.
#: Object keys the purge deliberately never deletes: shared reference data, not a user's file.
SHARED_REFERENCE_OBJECT_COLUMNS = {
    ("mark_schemes", "source_document"),  # uploads-bucket key (schemes/{id}/...), shared by all
}

NOT_OBJECT_COLUMNS = {
    ("subjects", "source_url"),  # reference data: where a syllabus came from
    ("syllabus_papers", "source_url"),
    ("syllabus_papers", "source_document"),  # provenance: the transcribed document's file name
    ("component_thresholds", "source_url"),
    ("option_thresholds", "source_url"),
    ("uploads", "idempotency_key"),  # a client-supplied dedupe token
    ("question_result_points", "group_key"),
    ("auth_cooldowns", "key_hash"),
    ("subject_topics", "keywords"),
    ("xp_events", "dedupe_key"),
    ("notifications", "dedupe_key"),
    ("email_outbox", "dedupe_key"),
    ("tutor_profiles", "documents_seen_at"),  # a timestamp
    ("tutor_approval_events", "documents_seen"),  # a boolean
}


def test_no_other_key_or_url_like_column_can_hide_an_object(engine: Engine) -> None:
    with engine.connect() as conn:
        found = {
            (r.table_name, r.column_name)
            for r in conn.execute(
                sa.text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND (column_name LIKE '%key%' "
                    "OR column_name LIKE '%document%' OR column_name LIKE '%url%')"
                )
            )
        }
    registered = {(c.table, c.column) for c in STORAGE_COLUMNS}
    unexplained = found - registered - NOT_OBJECT_COLUMNS - SHARED_REFERENCE_OBJECT_COLUMNS
    assert unexplained == set(), f"new key/url-like columns: register or allow-list {unexplained}"


# ── Unreferenced objects under a purged user's prefix (S4) ───────────────────


def test_objects_no_row_references_under_a_purged_users_prefix_are_swept(
    engine: Engine, world: World, local_settings: Settings, tmp_path: Path
) -> None:
    from lemely.io.storage_local import LocalFileStorageBackend

    backend = LocalFileStorageBackend(tmp_path)

    def put(bucket: str, key: str) -> None:
        target = tmp_path / bucket / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")

    def exists(bucket: str, key: str) -> bool:
        return (tmp_path / bucket / key).exists()

    stranger, keep = world.stranger, world.keep_student
    put(UP, f"uploads/{stranger}/orphan/scan.pdf")  # no row names it: swept
    put(UP, f"teacher/{world.stranger_teacher}/orphan/scan.pdf")
    put(AV, f"{stranger}/old-avatar.png")
    put(UP, f"uploads/{keep}/mine.pdf")  # a kept user's prefix: never listed
    put(AV, f"{keep}/mine.png")
    put(UP, f"uploads/{stranger}/shared.pdf")  # under a purged prefix, but a kept row owns it
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO uploads (user_id, storage_path) VALUES (:u, :p)"),
            {"u": keep, "p": f"uploads/{stranger}/shared.pdf"},
        )

    with engine.begin() as conn:
        plan = plan_purge(conn, KEEP)
    assert plan.unreferenced_objects == 0  # nothing listed until a storage backend is asked

    assert (
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=True, storage=backend) == 0
    )
    assert not exists(UP, f"uploads/{stranger}/orphan/scan.pdf")
    assert not exists(UP, f"teacher/{world.stranger_teacher}/orphan/scan.pdf")
    assert not exists(AV, f"{stranger}/old-avatar.png")
    assert exists(UP, f"uploads/{keep}/mine.pdf")
    assert exists(AV, f"{keep}/mine.png")
    assert exists(UP, f"uploads/{stranger}/shared.pdf"), "an object a kept row references"


def test_the_dry_run_counts_unreferenced_objects(
    engine: Engine,
    world: World,
    local_settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lemely.io.storage_local import LocalFileStorageBackend

    orphan = tmp_path / UP / f"uploads/{world.stranger}/orphan.pdf"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    storage = LocalFileStorageBackend(tmp_path)
    assert (
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False, storage=storage) == 0
    )
    out = capsys.readouterr().out
    assert "referenced by no row (found by prefix): 1" in out
    assert orphan.exists()


# ── GoTrue retry with --include-unverified-allowlisted (L1) ──────────────────


def test_a_failed_auth_deletion_of_an_unverified_allowlisted_user_is_retried(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    admin = FakeAdmin(_gotrue_users(engine), fail={world.unverified})
    assert _run(local_settings, admin, execute=True, include_unverified_allowlisted=True) == 1
    assert world.unverified not in _ids(engine)
    assert world.unverified in admin.users

    # Without the flag the row-less keep-domain user is left alone ...
    admin.fail.clear()
    assert _run(local_settings, admin, execute=True) == 0
    assert world.unverified in admin.users
    # ... and with it, the re-run finishes the job.
    assert _run(local_settings, admin, execute=True, include_unverified_allowlisted=True) == 0
    assert world.unverified not in admin.users
    assert {world.keep_student, world.keep_teacher} <= set(admin.users)


# ── The real mirror drops the old proof when the email changes (M3) ──────────


def test_the_db_mirror_clears_verification_when_the_email_changes(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    from lemely.auth.mirror import DbUserMirror

    mirror = DbUserMirror(local_settings)
    mirror.upsert(world.keep_student, email="DEV@lemelyig.com", role=Role.student)  # case only
    row = mirror.get_by_id(world.keep_student)
    assert row is not None and row.email_verified_at is not None
    mirror.upsert(world.keep_student, email="other@lemelyig.com", role=Role.student)
    row = mirror.get_by_id(world.keep_student)
    assert row is not None and row.email == "other@lemelyig.com"
    assert row.email_verified_at is None


# ── Flags: production and unrecognised are different refusals (L8) ───────────

UNKNOWN_URL = "postgresql+psycopg://u:p@db.unknown-host.example:5432/postgres"
PROD_URL = f"postgresql+psycopg://postgres.{PROD_REF}:pw@aws-0-eu.pooler.supabase.com:6543/postgres"


def test_the_production_flag_never_passes_an_unrecognised_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    settings = _settings(database={"url": UNKNOWN_URL})
    with pytest.raises(click.ClickException, match="cannot recognise") as caught:
        _run(settings, FakeAdmin([]), execute=False, allow_production=True)
    assert "--target-is-unrecognised" in caught.value.message


def test_the_unrecognised_flag_passes_only_an_unrecognised_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    # Production-looking target with only the unrecognised flag: still refused.
    with pytest.raises(click.ClickException, match="production target"):
        purge_cli.purge_users_command(
            _settings(database={"url": PROD_URL}),
            keep_domains=KEEP,
            execute=False,
            include_unverified_allowlisted=False,
            allow_production=False,
            allow_unrecognised=True,
            json_output=False,
            admin=FakeAdmin([]),
        )
    # Unrecognised target with its own flag: gets as far as the engine.
    with pytest.raises(AssertionError, match="asked for a database engine"):
        purge_cli.purge_users_command(
            _settings(database={"url": UNKNOWN_URL}),
            keep_domains=KEEP,
            execute=False,
            include_unverified_allowlisted=False,
            allow_production=False,
            allow_unrecognised=True,
            json_output=False,
            admin=FakeAdmin([]),
        )


def test_the_cli_exposes_the_unrecognised_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_DATABASE__URL", UNKNOWN_URL)
    monkeypatch.setattr(purge_cli, "get_engine", _NoConnect())
    result = CliRunner().invoke(
        cli,
        ["admin", "purge-users", "--keep-domain", "lemelyig.com", "--i-know-this-is-production"],
    )
    assert result.exit_code != 0 and "--target-is-unrecognised" in result.output


# ── Privileged accounts in the delete list (L7) ──────────────────────────────


def test_privileged_accounts_in_the_delete_list_are_called_out_loudly(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(engine) as session, session.begin():
        _user(session, "boss@gmail.com", role=Role.platform_admin)
        _user(session, "head@school.example", role=Role.school_admin)
    _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False)
    out = capsys.readouterr().out
    summary = out.split("=== ACCOUNTS TO DELETE")[0]
    assert "!!! 2 PRIVILEGED ACCOUNT(S) IN THE DELETE LIST" in summary
    assert "boss@gmail.com" in summary and "head@school.example" in summary
    assert "stranger@example.com" not in summary.split("!!!")[1].split("===")[0]


def test_no_privileged_banner_when_none_would_be_deleted(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=False)
    assert "PRIVILEGED" not in capsys.readouterr().out


# ── uuid columns with no foreign key (L5) ────────────────────────────────────


def test_every_uuid_column_without_a_foreign_key_has_a_recorded_disposition(
    engine: Engine,
) -> None:
    with engine.connect() as conn:
        found = {
            (r.table_name, r.column_name)
            for r in conn.execute(
                sa.text(
                    """
                    SELECT c.table_name, c.column_name FROM information_schema.columns c
                    WHERE c.table_schema = 'public' AND c.data_type = 'uuid'
                      AND c.table_name <> 'alembic_version'
                      AND NOT EXISTS (
                        SELECT 1 FROM pg_constraint con
                        JOIN pg_class cl ON cl.oid = con.conrelid
                        JOIN pg_attribute a ON a.attrelid = con.conrelid
                          AND a.attnum = ANY (con.conkey)
                        WHERE con.contype IN ('f', 'p') AND cl.relname = c.table_name
                          AND a.attname = c.column_name)
                    """
                )
            )
        }
    assert found == set(NON_FK_UUID_COLUMNS), (
        f"uuid column(s) with no foreign key: record them in NON_FK_UUID_COLUMNS "
        f"(or add handling): {found ^ set(NON_FK_UUID_COLUMNS)}"
    )


def test_a_friendship_with_a_purged_user_goes_even_though_its_pair_columns_have_no_fk(
    engine: Engine, world: World
) -> None:
    low, high = sorted([world.keep_student, world.stranger])
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO friendships (requester_id, addressee_id, pair_low, pair_high, status) "
                "VALUES (:r, :a, :l, :h, 'accepted')"
            ),
            {"r": world.keep_student, "a": world.stranger, "l": low, "h": high},
        )
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    assert _count(engine, "friendships") == 0
    assert world.keep_student in _ids(engine)


# ── Regressions from the first staging run (execution lemely-purge-staging-ftlsl) ────────────


def test_an_invite_created_by_a_purged_user_does_not_block_execute(
    engine: Engine, world: World
) -> None:
    """``invites.created_by`` is NO ACTION; the same row is also reachable by CASCADE.

    A parent invite names the child (``child_id``, CASCADE) and its creator (``created_by``,
    NO ACTION). When both are purged the row is first doomed through the cascade, and the walker
    used to skip the explicit delete the NO ACTION foreign key needs, so ``DELETE FROM users``
    failed with ``fk_invites_created_by_users``.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO invites (code, role, child_id, created_by) "
                "VALUES ('PARENT01', 'parent', :child, :creator)"
            ),
            {"child": world.stranger, "creator": world.stranger_teacher},
        )
        conn.execute(
            sa.text(
                "INSERT INTO invites (code, role, child_id, created_by) "
                "VALUES ('PARENT02', 'parent', :child, :creator)"
            ),
            {"child": world.stranger_teacher, "creator": world.stranger},
        )
    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    assert _ids(engine) == world.kept | {world.unverified}
    with engine.connect() as conn:
        left = conn.execute(sa.text("SELECT count(*) FROM invites WHERE code='PARENT01'"))
        assert left.scalar_one() == 0


class ListingStorage(FakeStorage):
    """A bucket that really holds keys: deleting a missing key is a no-op, listing is by prefix."""

    def __init__(self, keys: dict[str, set[str]], *, fail: set[str] | None = None) -> None:
        super().__init__(fail=fail)
        self.keys = keys

    def delete(self, bucket: str, object_path: str) -> None:
        super().delete(bucket, object_path)
        self.keys.get(bucket, set()).discard(object_path)

    def list_objects(self, bucket: str, prefix: str) -> list[str]:
        return sorted(k for k in self.keys.get(bucket, set()) if k.startswith(prefix))


def test_a_database_failure_deletes_no_storage_object_and_no_auth_user(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB step raising (as on staging) must leave every file and Auth user in place."""

    def _boom(_conn: sa.Connection, _plan: object) -> dict[str, int]:
        raise sa.exc.IntegrityError("DELETE FROM users", {}, Exception("fk_invites_created_by"))

    monkeypatch.setattr(purge_cli, "execute_purge", _boom)
    everyone = _ids(engine)
    storage = FakeStorage()
    admin = FakeAdmin(_gotrue_users(engine))
    with pytest.raises(click.ClickException, match="rolled back"):
        _run(local_settings, admin, execute=True, storage=storage)
    assert storage.deleted == [], "storage objects were deleted although the database step failed"
    assert admin.delete_calls == [], "Auth users were deleted although the database step failed"
    assert _ids(engine) == everyone


def test_a_rerun_after_a_partial_storage_failure_finishes_cleanly(
    engine: Engine, world: World, local_settings: Settings
) -> None:
    """Rows are gone, one object failed: a rerun sweeps the rest; missing objects are fine."""
    stranger = world.stranger
    avatars = {f"{stranger}/a.png", f"{stranger}/b.png"}
    uploads = {f"uploads/{stranger}/x.pdf"}
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET avatar_path=:p WHERE id=:u"),
            {"p": f"{stranger}/a.png", "u": stranger},
        )
    bucket_keys = {AV: set(avatars), UP: set(uploads), EV: set()}
    admin = FakeAdmin(_gotrue_users(engine))
    first = ListingStorage(bucket_keys, fail={f"{stranger}/a.png"})
    assert _run(local_settings, admin, execute=True, storage=first) == 1
    assert _ids(engine) == world.kept | {world.unverified}, "the database step did not commit"
    assert admin.delete_calls == [], "Auth users went although storage is incomplete"
    assert bucket_keys[AV] == {f"{stranger}/a.png"}, "only the failing object should remain"

    # The cause is fixed; the other objects are already missing, which must not matter.
    healthy = ListingStorage(bucket_keys)
    assert _run(local_settings, admin, execute=True, storage=healthy) == 0
    assert bucket_keys == {AV: set(), UP: set(), EV: set()}
    assert stranger in admin.delete_calls
    assert {u.id for u in admin.list_users()} >= world.kept


def test_a_failed_key_inside_a_swept_folder_is_not_listed_for_hand_deletion(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keys under ``{user}/`` are found again by the rerun, so no by-hand list is printed."""
    stranger = world.stranger
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET avatar_path=:p WHERE id=:u"),
            {"p": f"{stranger}/a.png", "u": stranger},
        )
    keys = {AV: {f"{stranger}/a.png"}, UP: set(), EV: set()}
    storage = ListingStorage(keys, fail={f"{stranger}/a.png"})
    admin = FakeAdmin(_gotrue_users(engine))
    assert _run(local_settings, admin, execute=True, storage=storage) == 1
    assert "by hand" not in capsys.readouterr().err.lower()


def test_failed_keys_outside_the_swept_folders_are_in_the_json_report(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = FakeStorage(fail={"av/stranger.png"})
    admin = FakeAdmin(_gotrue_users(engine))
    code = _run(local_settings, admin, execute=True, storage=storage, json_output=True)
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["objectsFailedByHand"] == [["lemely-avatars", "av/stranger.png"]]


def test_the_auth_count_says_skipped_when_a_storage_failure_stopped_the_auth_step(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    storage = FakeStorage(fail={"av/stranger.png"})
    assert _run(local_settings, admin, execute=True, storage=storage) == 1
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("Supabase Auth users"))
    assert "skipped" in line and "object" in line, line
    assert admin.delete_calls == []


def test_the_auth_json_says_skipped_when_a_storage_failure_stopped_the_auth_step(
    engine: Engine,
    objects_world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine))
    storage = FakeStorage(fail={"av/stranger.png"})
    assert _run(local_settings, admin, execute=True, storage=storage, json_output=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["authSkipped"] is True
    assert "object" in report["authSkippedReason"]
    assert report["authDeleted"] == 0


def test_the_auth_count_is_the_number_actually_deleted(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = FakeAdmin(_gotrue_users(engine), fail={world.stranger})
    assert _run(local_settings, admin, execute=True) == 1
    out = capsys.readouterr().out
    expected = len(world.disallowed) - 1  # one deletion failed
    assert f"Supabase Auth users deleted: {expected}" in out


def test_orphans_are_listed_with_their_email_and_swept_folders_in_a_dry_run(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    orphan = GoTrueUser(id=uuid.uuid4(), email="gone@example.com")
    admin = FakeAdmin([*_gotrue_users(engine), orphan])
    assert _run(local_settings, admin, execute=False) == 0
    out = capsys.readouterr().out
    assert str(orphan.id) in out and "gone@example.com" in out
    assert f"uploads/{orphan.id}/" in out and f"teacher/{orphan.id}/" in out
    assert f"{orphan.id}/" in out

    assert _run(local_settings, admin, execute=False, json_output=True) == 0
    report = json.loads(capsys.readouterr().out)
    [entry] = report["orphans"]
    assert entry["id"] == str(orphan.id) and entry["email"] == "gone@example.com"
    assert f"lemely-uploads/uploads/{orphan.id}/" in entry["folders"]
    assert f"lemely-avatars/{orphan.id}/" in entry["folders"]


def test_orphans_are_listed_when_executing_too(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    orphan = GoTrueUser(id=uuid.uuid4(), email="gone@example.com")
    admin = FakeAdmin([*_gotrue_users(engine), orphan])
    assert _run(local_settings, admin, execute=True) == 0
    out = capsys.readouterr().out
    assert str(orphan.id) in out and "gone@example.com" in out


class _ListingFails(FakeAdmin):
    def list_users(self) -> list[GoTrueUser]:
        raise RuntimeError("503 from GoTrue")


def test_execute_changes_nothing_when_the_auth_listing_fails(
    engine: Engine, objects_world: World, local_settings: Settings
) -> None:
    everyone = _ids(engine)
    storage = FakeStorage()
    admin = _ListingFails(_gotrue_users(engine))
    with pytest.raises(click.ClickException, match="nothing was changed"):
        _run(local_settings, admin, execute=True, storage=storage)
    assert _ids(engine) == everyone
    assert storage.deleted == [] and admin.delete_calls == []


def test_a_dry_run_warns_and_continues_when_the_auth_listing_fails(
    engine: Engine,
    world: World,
    local_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin = _ListingFails(_gotrue_users(engine))
    assert _run(local_settings, admin, execute=False) == 0
    assert "Supabase Auth step failed" in capsys.readouterr().err


def test_a_database_error_with_an_empty_message_is_still_reported(
    engine: Engine,
    world: World,
    local_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_conn: sa.Connection, _plan: object) -> dict[str, int]:
        raise sa.exc.OperationalError("DELETE", {}, Exception(""))

    monkeypatch.setattr(purge_cli, "execute_purge", _boom)
    with pytest.raises(click.ClickException, match="rolled back"):
        _run(local_settings, FakeAdmin(_gotrue_users(engine)), execute=True)


def test_a_failure_while_committing_does_not_claim_a_rollback(
    engine: Engine,
    world: World,
    local_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the commit itself raises, the server may have committed: say so, point at a dry run."""

    def _commit_fails(_self: object) -> None:
        raise sa.exc.OperationalError("COMMIT", {}, Exception("connection lost"))

    monkeypatch.setattr(sa.engine.Connection, "_commit_impl", _commit_fails)
    storage = FakeStorage()
    admin = FakeAdmin(_gotrue_users(engine))
    with pytest.raises(click.ClickException) as raised:
        _run(local_settings, admin, execute=True, storage=storage)
    message = raised.value.message
    assert "dry run" in message and "was rolled back" not in message
    assert storage.deleted == [] and admin.delete_calls == []


# ── Every foreign key into users is covered ──────────────────────────────────

_FK_INTO_USERS_SQL = sa.text(
    """
    SELECT cl.relname AS child, a.attname AS col, con.confdeltype::text AS on_delete
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_class p ON p.oid = con.confrelid
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
    WHERE con.contype = 'f' AND p.relname = 'users'
      AND p.relnamespace = 'public'::regnamespace AND cl.relname <> 'users'
    ORDER BY 1, 2
    """
)

_COLUMNS_SQL = sa.text(
    """
    SELECT column_name, data_type, udt_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :t AND is_nullable = 'NO'
      AND column_default IS NULL AND is_identity = 'NO' AND is_generated = 'NEVER'
      AND generation_expression IS NULL
    """
)


_PARENT_FKS_SQL = sa.text(
    """
    SELECT a.attname, pcl.relname, pa.attname
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_class pcl ON pcl.oid = con.confrelid
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
    JOIN pg_attribute pa ON pa.attrelid = con.confrelid AND pa.attnum = con.confkey[1]
    WHERE con.contype = 'f' AND array_length(con.conkey, 1) = 1
      AND cl.relname = :t AND cl.relnamespace = 'public'::regnamespace
      AND pcl.relname <> 'users'
    """
)


def _unique_word() -> str:
    """Letters only (a tutor's first name rejects digits), different on every call."""
    return "x" + uuid.uuid4().hex[:12].translate(str.maketrans("0123456789", "ghijklmnop"))


def _value_for(conn: sa.Connection, data_type: str, udt_name: str) -> object:
    """A throwaway value for a NOT NULL column with no default, enough to satisfy CHECKs."""
    if data_type == "USER-DEFINED":
        label = conn.execute(
            sa.text(
                "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = :n ORDER BY e.enumsortorder LIMIT 1"
            ),
            {"n": udt_name},
        ).scalar_one()
        return sa.literal_column(f"'{label}'::{udt_name}")
    return {
        "uuid": sa.literal_column("gen_random_uuid()"),
        # Unique, because parent rows (a subject's code, say) must not collide with each other.
        "text": _unique_word(),
        "character varying": _unique_word(),
        "integer": 1,
        "smallint": 1,
        "bigint": 1,
        "numeric": 1,
        "double precision": 1.0,
        "boolean": False,
        "jsonb": sa.literal_column("'{}'::jsonb"),
        "json": sa.literal_column("'{}'::json"),
        "ARRAY": sa.literal_column("'{}'"),
        "date": sa.literal_column("current_date"),
        "timestamp with time zone": sa.literal_column("now()"),
        "timestamp without time zone": sa.literal_column("now()"),
        "time without time zone": sa.literal_column("current_time"),
        "bytea": b"x",
    }[data_type]


#: Foreign keys into ``users`` that cannot be seeded together. Every single column is seeded, with
#: the values its table's CHECK constraints need in :func:`_overrides`; an entry here is a
#: combined row (columns joined by ``+``) the schema itself forbids. The test below fails if a
#: foreign key can be neither seeded nor listed here.
NOT_GENERICALLY_SEEDABLE: dict[tuple[str, str], str] = {
    ("quizzes", "student_id+teacher_id"): "ck_quizzes_owner_xor: a quiz has one owner, so both "
    "columns can never be set on one row; each is seeded alone in phase one",
}


def _overrides(table: str, column: str, user_id: uuid.UUID) -> dict[str, object]:
    """Column values a table's CHECK constraints need, beyond the generic NOT NULL fill."""
    lit = sa.literal_column
    nobody = "'00000000-0000-0000-0000-000000000000'::uuid"
    this = f"'{user_id}'::uuid"
    start = "now() - interval '2 days'"
    by_table: dict[str, dict[str, object]] = {
        # requester <> addressee and pair_low < pair_high, whichever side is the purged user.
        "friendships": {
            "requester_id": lit(nobody),
            "addressee_id": lit(nobody),
            "pair_low": lit(nobody),
            "pair_high": lit(this),
        },
        "invites": {
            "child_id": lit("gen_random_uuid()"),
            "code": f"fk-{user_id.hex[:20]}",
        },
        # exactly one of class_id / student_id, and kind must match which owner is set.
        "quiz_assignments": {"class_id": lit("gen_random_uuid()")},
        "quizzes": {
            "kind": lit("'teacher'::quizkind" if column == "teacher_id" else "'practice'::quizkind")
        },
        "review_queue": {"attempt_id": lit("gen_random_uuid()")},
        "tutor_profiles": {"offers_virtual": True},
        "tutor_bookings": {
            "starts_at": lit(start),
            "ends_at": lit(f"{start} + interval '1 hour'"),
        },
        "tutoring_reports": {
            "tutor_profile_id": lit("gen_random_uuid()"),
            "target_type": lit("'tutor_profile'::reporttargettype"),
        },
    }
    values = dict(by_table.get(table, {}))
    if table == "quiz_assignments" and column == "student_id":
        values = {}  # the check wants class_id NULL when student_id is set
    return values


def _combined_overrides(table: str, users: dict[str, uuid.UUID]) -> dict[str, object]:
    """:func:`_overrides` for one row that sets *every* users-FK column of ``table`` at once."""
    lit = sa.literal_column
    values: dict[str, object] = {}
    for column, user_id in users.items():
        values.update(_overrides(table, column, user_id))
    if table == "friendships":
        low, high = sorted((users["requester_id"], users["addressee_id"]))
        values.update(pair_low=low, pair_high=high)
    if table == "quiz_assignments" and "student_id" in users:
        values.pop("class_id", None)  # the check wants class_id NULL when student_id is set
    if table == "quizzes":
        kind = "teacher" if "teacher_id" in users else "practice"
        values["kind"] = lit(f"'{kind}'::quizkind")
    return values


def test_every_foreign_key_into_users_is_deleted_or_cleared_before_users(engine: Engine) -> None:
    """Doomed users referenced through *each* foreign key, and through all of a table's at once.

    The foreign keys come from ``pg_constraint`` of the migrated schema, so a migration that adds
    one is exercised here automatically. Each referencing row is seeded with foreign-key
    enforcement off (``session_replication_role = replica``) so other columns need no parents;
    the purge itself then runs with enforcement on, exactly as in production, and ``DELETE FROM
    users`` raises if any row still points at a purged user.

    Phase one seeds one row per (table, column) and purges. Phase two seeds, for every table with
    more than one foreign key into ``users``, rows whose every such column names a *different*
    doomed user, and purges again. That is the staging failure: ``invites`` is reached by CASCADE
    (``child_id``) and by NO ACTION (``created_by``) from two purged users, and a walker that
    treats a row it already reached as finished skips the NO ACTION delete and fails ``DELETE FROM
    users``. Phase one alone cannot see that: no row there has two foreign keys at doomed users,
    and a single row left on the NO ACTION edge keeps the walker's delete step alive. With that
    walker restored (hunk reverted, 3 of 3 runs) this test fails on
    ``fk_invites_created_by_users``.
    """
    seeded: list[tuple[str, str]] = []
    seeded_multi: list[str] = []
    skipped: list[tuple[str, str, str]] = []
    counter = 0

    def doomed_user(conn: sa.Connection, user_id: uuid.UUID | None = None) -> uuid.UUID:
        nonlocal counter
        counter += 1
        user_id = user_id or uuid.uuid4()
        conn.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:i, :e, 'student')"),
            {"i": user_id, "e": f"doomed-{counter}@fk.example"},
        )
        return user_id

    def seed(
        conn: sa.Connection,
        table: str,
        values: dict[str, object],
        keep: set[str],
        depth: int = 0,
    ) -> str:
        """Insert one row and the parent rows it names; return the database error, or "" if ok.

        Parents are real rows, not dangling ids: the purge updates a row it already updated once
        (``review_queue.assigned_to`` then ``resolved_by``), and PostgreSQL re-checks every
        foreign key of a row version the same transaction wrote, so a dangling parent would fail
        that second update for a reason that has nothing to do with users.
        """
        for name, data_type, udt in conn.execute(_COLUMNS_SQL, {"t": table}).all():
            if name not in values and name not in keep:
                values[name] = _value_for(conn, data_type, udt)
        if depth < 6:
            for column, parent, parent_column in conn.execute(_PARENT_FKS_SQL, {"t": table}):
                value = values.get(column)
                if value is None or parent == table:
                    continue
                if isinstance(value, sa.sql.elements.ColumnClause):  # gen_random_uuid()
                    value = values[column] = uuid.uuid4()
                parent_values = _overrides(parent, "", uuid.UUID(int=0))
                parent_values[parent_column] = value
                if parent == "quizzes":  # ck_quizzes_owner_xor wants exactly one owner
                    parent_values["student_id"] = doomed_user(conn)
                error = seed(conn, parent, parent_values, {parent_column}, depth + 1)
                if error:
                    return f"parent {parent}: {error}"
        tbl = sa.table(table, *[sa.column(c) for c in values])
        try:
            with conn.begin_nested():
                conn.execute(sa.insert(tbl).values(values))
        except sa.exc.DBAPIError as exc:
            return str(exc.orig).splitlines()[0]
        return ""

    with engine.begin() as conn:
        refs = [(r.child, r.col) for r in conn.execute(_FK_INTO_USERS_SQL)]
        by_table: dict[str, list[str]] = {}
        for table, column in refs:
            by_table.setdefault(table, []).append(column)
        conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
        for table, column in refs:
            user_id = doomed_user(conn)
            values: dict[str, object] = _overrides(table, column, user_id)
            values[column] = user_id
            error = seed(conn, table, values, {column})
            if error:
                skipped.append((table, column, error))
                conn.execute(sa.text("DELETE FROM users WHERE id = :i"), {"i": user_id})
            else:
                seeded.append((table, column))
    unexplained = [s for s in skipped if (s[0], s[1]) not in NOT_GENERICALLY_SEEDABLE]
    assert not unexplained, f"could not seed a row for these foreign keys: {unexplained}"
    assert len(seeded) + len(skipped) == len(refs) and seeded

    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    assert _ids(engine) == set(), "a doomed user survived the purge (one foreign key per row)"

    # Phase two is a purge of its own: if phase one's rows were still there, one of them would
    # keep the walker's NO ACTION step alive and hide the bug. Here every row on a table's edges
    # is a combined row, so a walker that skips a row it already reached has nothing to fall
    # back on.
    with engine.begin() as conn:
        conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
        for table, columns in by_table.items():
            if len(columns) < 2:
                continue
            # Two rows with fresh users, the columns taking them in opposite id order. ``DELETE
            # FROM users WHERE id IN (...)`` removes users in id order, and whether a NO ACTION
            # key is checked before or after its row's cascade depends on which column names the
            # user deleted first. One order passes even with the staging bug; both must pass.
            for ordering in (columns, columns[::-1]):
                ids = sorted(uuid.uuid4() for _ in columns)
                owners = zip(ordering, ids, strict=True)
                users = {column: doomed_user(conn, uid) for column, uid in owners}
                values = _combined_overrides(table, users)
                values.update(users)
                error = seed(conn, table, values, set(columns))
                if error:
                    skipped.append((table, "+".join(sorted(columns)), error))
                else:
                    seeded_multi.append(table)
    unexplained = [s for s in skipped if (s[0], s[1]) not in NOT_GENERICALLY_SEEDABLE]
    assert not unexplained, f"could not seed a row for these foreign keys: {unexplained}"
    assert "invites" in seeded_multi, seeded_multi

    with engine.begin() as conn:
        execute_purge(conn, plan_purge(conn, KEEP))
    assert _ids(engine) == set(), "a doomed user survived the purge (every foreign key at once)"
