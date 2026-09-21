"""US-038 acceptance: migration ``0038_marker_source_dropped``.

Three properties, each requiring the *real* migration to run (not
``Base.metadata.create_all``, which only reflects the current ORM state and
never executes a migration's data steps — see ``test_migration_0037_remove_
ai_detection.py``'s own module docstring, and ``migrated_sessionmaker`` in
``tests/conftest.py``):

* Schema round-trip on an EMPTY database: ``upgrade`` then ``downgrade``
  leaves the ``markersource`` enum and ``question_results`` columns exactly
  as they were before ``upgrade`` ran.
* ``upgrade`` adds ``"dropped"`` as a valid ``markersource`` member, and a
  row seeded with it round-trips unchanged.
* ``downgrade`` cannot keep a row persisted as ``"dropped"`` (the value is
  about to stop existing) — it rewrites such a row to ``"missing"`` (the
  same interim mapping ``attempt_repo.py`` used to perform on write) before
  the enum is rebuilt without the member. ``needs_teacher_review`` on that
  row is untouched by either direction — the protective column is
  independent of the marker-source enum.

Each test builds its own throwaway database, stopped at a specific revision
rather than always going to ``head``, mirroring ``test_migration_0037_
remove_ai_detection.py``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError

from lemely.runtime.config import DatabaseSettings

_PRE_MIGRATION_REVISION = "0037_remove_ai_detection"
_MIGRATION_REVISION = "0038_marker_source_dropped"
_MIGRATION_FILE = (
    Path(__file__).resolve().parents[1]
    / "lemely"
    / "db"
    / "migrations"
    / "versions"
    / f"{_MIGRATION_REVISION}.py"
)


def _server_reachable(base_url: str) -> bool:
    server_url = make_url(base_url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@contextmanager
def _throwaway_db() -> Iterator[tuple[Config, Engine]]:
    """An empty throwaway Postgres database plus an Alembic ``Config`` bound to it.

    Mirrors ``test_migration_0037_remove_ai_detection.py``'s ``_throwaway_db``
    (same env-var routing rationale — ``lemely/db/migrations/env.py``
    re-derives the URL from ``load_settings()``, so
    ``LEMELY_DATABASE__URL`` is what actually steers
    ``command.upgrade``/``command.downgrade``, not ``cfg.set_main_option``)
    but yields the ``Config`` itself instead of always upgrading to
    ``head``, so callers can drive specific revisions.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig0038_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    url = make_url(base_url).set(database=dbname)
    rendered_url = url.render_as_string(hide_password=False)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", rendered_url)
    previous_db_url = os.environ.get("LEMELY_DATABASE__URL")
    os.environ["LEMELY_DATABASE__URL"] = rendered_url
    engine = create_engine(url)
    try:
        yield cfg, engine
    finally:
        os.environ.pop("LEMELY_DATABASE__URL", None)
        if previous_db_url is not None:
            os.environ["LEMELY_DATABASE__URL"] = previous_db_url
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _enum_members(engine: Engine, enum_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = :name"
            ),
            {"name": enum_name},
        ).all()
    return {r[0] for r in rows}


def _columns(engine: Engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :name"),
            {"name": table_name},
        ).all()
    return {r[0] for r in rows}


def _seed_user_and_attempt(conn: sa.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'student')"),
        {"id": user_id, "email": f"{user_id}@example.test"},
    )
    attempt_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO attempts "
            "(id, user_id, awarded_marks, maximum_marks, percentage, recorded_at) "
            "VALUES (:id, :user_id, 1, 1, 100.0, now())"
        ),
        {"id": attempt_id, "user_id": user_id},
    )
    return attempt_id


def _seed_question_result(
    engine: Engine, *, marker_source: str, needs_teacher_review: bool = False
) -> uuid.UUID:
    """Seed one user + attempt + a ``question_results`` row with the given ``marker_source``.

    Raw SQL, not the ORM: at ``_PRE_MIGRATION_REVISION`` (before this
    migration) Postgres's ``markersource`` enum does not yet have
    ``"dropped"`` at all, so a test seeding a ``dropped`` row must run
    against the schema this migration itself produces (post-upgrade), which
    only raw SQL against a specific revision lets us pin.
    """
    qr_id = uuid.uuid4()
    with engine.begin() as conn:
        attempt_id = _seed_user_and_attempt(conn)
        conn.execute(
            sa.text(
                "INSERT INTO question_results "
                "(id, attempt_id, question_id, awarded_marks, maximum_marks, "
                " confidence_band, confidence_score, marker_source, needs_teacher_review) "
                "VALUES (:id, :attempt_id, '1', 0, 1, 'low', 0.0, "
                " CAST(:marker_source AS markersource), :needs_teacher_review)"
            ),
            {
                "id": qr_id,
                "attempt_id": attempt_id,
                "marker_source": marker_source,
                "needs_teacher_review": needs_teacher_review,
            },
        )
    return qr_id


class TestLockTimeoutIsAlwaysReset:
    """Mirrors ``test_migration_0037_remove_ai_detection.py``'s own guard:
    ``env.py`` shares one transaction across every migration a single
    ``alembic upgrade``/``downgrade`` invocation applies
    (``transaction_per_migration`` unset), so a ``SET lock_timeout`` with no
    matching ``RESET`` before ``upgrade()``/``downgrade()`` returns would
    silently keep applying to whatever migration runs next in the same
    invocation. Static, not a runtime probe — nothing behavioural can
    distinguish a leaked session-level setting from a fresh connection's own
    default once the migration's connection is closed."""

    def test_upgrade_and_downgrade_each_reset_the_lock_timeout_they_set(self) -> None:
        source = _MIGRATION_FILE.read_text()
        for name in ("upgrade", "downgrade"):
            body = source.split(f"def {name}()", 1)[1]
            body = body.split("\ndef ", 1)[0]
            assert "SET lock_timeout = " in body, f"{name}() never sets lock_timeout"
            assert "RESET lock_timeout" in body, f"{name}() never resets lock_timeout"
            assert body.index("RESET lock_timeout") > body.index("SET lock_timeout = "), (
                f"{name}()'s RESET must come after its SET"
            )


class TestSchemaRoundTrip:
    """Upgrade then downgrade on an empty DB leaves the schema identical."""

    def test_enum_members_restored(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _enum_members(engine, "markersource")
            assert before == {"deterministic", "ai", "missing"}

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _enum_members(engine, "markersource")
            assert during == {"deterministic", "ai", "missing", "dropped"}

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _enum_members(engine, "markersource")
            assert after == before

    def test_question_results_columns_unchanged(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _columns(engine, "question_results")

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _columns(engine, "question_results")
            assert during == before  # this migration adds no column, only an enum member

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _columns(engine, "question_results")
            assert after == before


class TestDroppedMemberRoundTrip:
    """``upgrade`` adds ``"dropped"``; a row persisted with it round-trips."""

    def test_dropped_is_a_valid_member_after_upgrade(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine, marker_source="dropped", needs_teacher_review=True
            )

            with engine.connect() as conn:
                marker_source, needs_review = conn.execute(
                    sa.text(
                        "SELECT marker_source, needs_teacher_review "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert marker_source == "dropped"
            # The protective column is independent of marker_source: a
            # dropped question that needed review must still be flagged.
            assert needs_review is True


class TestDowngradeCannotKeepDropped:
    """``downgrade`` cannot preserve the ``"dropped"`` distinction — the
    module docstring's recorded decision is to rewrite such a row to
    ``"missing"`` (the same mapping ``attempt_repo.py`` used to perform on
    write) before the enum is rebuilt without the member."""

    def test_a_dropped_row_becomes_missing_on_downgrade(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine, marker_source="dropped", needs_teacher_review=True
            )

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                marker_source, needs_review = conn.execute(
                    sa.text(
                        "SELECT marker_source, needs_teacher_review "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert marker_source == "missing"
            # needs_teacher_review is a separate column, untouched by the
            # marker_source rewrite — the protective flag must survive even
            # though the finer distinction cannot.
            assert needs_review is True

    def test_a_missing_row_is_unaffected_by_downgrade(self) -> None:
        """The false-positive direction: a row that was genuinely ``"missing"``
        (never ``"dropped"``) before downgrade must not be touched by the
        rewrite's ``WHERE`` clause."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, marker_source="missing")

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                marker_source = conn.execute(
                    sa.text("SELECT marker_source FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
            assert marker_source == "missing"
