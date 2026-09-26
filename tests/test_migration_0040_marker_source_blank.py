"""Task #36 acceptance: migration ``0040_marker_source_blank``.

The migration does two things in one enum rebuild, because the user approved the
marking-cache hash budget ONCE: it adds ``"blank"`` to the ``markersource``
Postgres enum and it drops ``question_results.plagiarism_flagged``.

Properties, each requiring the *real* migration to run (not
``Base.metadata.create_all``, which only reflects the current ORM state and
never executes a migration's data steps — see ``migrated_sessionmaker`` in
``tests/conftest.py``):

* Schema round-trip on an EMPTY database: ``upgrade`` then ``downgrade`` leaves
  the ``markersource`` enum and the ``question_results`` columns exactly as they
  were, ``plagiarism_flagged`` included, with its nullability and server default.
* ``upgrade`` makes ``"blank"`` a valid member and a row seeded with it
  round-trips; ``upgrade`` removes the column.
* ``downgrade`` cannot keep a row persisted as ``"blank"`` — it rewrites it to
  ``"missing"``, the exact value it carried before this migration — and does not
  touch rows that were never ``"blank"``.
* Both directions reset the ``lock_timeout`` they set.

Structured after ``tests/test_migration_0038_marker_source_dropped.py``, which
this migration follows as precedent, including its own throwaway-database
helper: each test builds its own database and stops at a specific revision
rather than always going to ``head``.
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

_PRE_MIGRATION_REVISION = "0039_merge_heads"
_MIGRATION_REVISION = "0040_marker_source_blank"
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

    Same env-var routing rationale as the ``0038``/``0037`` migration tests:
    ``lemely/db/migrations/env.py`` re-derives the URL from ``load_settings()``,
    so ``LEMELY_DATABASE__URL`` is what actually steers
    ``command.upgrade``/``command.downgrade``, not ``cfg.set_main_option``.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig0040_{uuid.uuid4().hex[:12]}"
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


def _column_shapes(engine: Engine, table_name: str) -> dict[str, tuple[str, str, str | None]]:
    """Every column's name, type, nullability and default.

    Names alone would let ``downgrade`` re-add ``plagiarism_flagged`` as a
    nullable column with no default and still pass — a schema that accepts rows
    this branch's ``_to_question_result`` would leave NULL.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = :name"
            ),
            {"name": table_name},
        ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


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

    Raw SQL, not the ORM: at ``_PRE_MIGRATION_REVISION`` the ``markersource``
    enum has no ``"blank"`` member at all, so a test seeding a ``blank`` row must
    run against the schema this migration itself produces.
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
    """``env.py`` shares one transaction across every migration a single
    ``alembic upgrade``/``downgrade`` invocation applies
    (``transaction_per_migration`` unset), so a ``SET lock_timeout`` with no
    matching ``RESET`` before returning would silently keep applying to whatever
    migration runs next. Static, not a runtime probe — nothing behavioural can
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
            assert before == {"deterministic", "ai", "missing", "dropped"}

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _enum_members(engine, "markersource")
            assert during == {"deterministic", "ai", "missing", "dropped", "blank"}

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            assert _enum_members(engine, "markersource") == before

    def test_the_plagiarism_column_is_dropped_and_restored_in_full(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _column_shapes(engine, "question_results")
            assert "plagiarism_flagged" in before
            # `0039_merge_heads` already dropped the detector's twin.
            assert "ai_detection_flagged" not in before

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _column_shapes(engine, "question_results")
            assert "plagiarism_flagged" not in during
            assert set(before) - set(during) == {"plagiarism_flagged"}

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _column_shapes(engine, "question_results")
            # Type, nullability AND default, not just the name: the column must
            # come back exactly as `0037_question_result_pts` created it.
            assert after == before


class TestBlankMemberRoundTrip:
    """``upgrade`` adds ``"blank"``; a row persisted with it round-trips."""

    def test_blank_is_a_valid_member_after_upgrade(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, marker_source="blank")

            with engine.connect() as conn:
                marker_source, needs_review = conn.execute(
                    sa.text(
                        "SELECT marker_source, needs_teacher_review "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert marker_source == "blank"
            # US-039's ruling, at the storage layer: a blank is an UNFLAGGED
            # zero. The value carries that on its own now, so nothing has to
            # read `review_reason` to find it.
            assert needs_review is False


class TestDowngradeCannotKeepBlank:
    """``downgrade`` cannot preserve the ``"blank"`` distinction — the member is
    about to stop existing, so such a row is rewritten to ``"missing"``, the
    exact value it carried before this migration."""

    def test_a_blank_row_becomes_missing_on_downgrade(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, marker_source="blank")

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                marker_source, needs_review, plagiarism = conn.execute(
                    sa.text(
                        "SELECT marker_source, needs_teacher_review, plagiarism_flagged "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert marker_source == "missing"
            # Both other columns are independent of the rewrite. The re-added
            # `plagiarism_flagged` comes back at its server default for every
            # existing row — the upgrade does not keep the values, and the
            # `plagiarism_flag` review_queue rows are the surviving record.
            assert needs_review is False
            assert plagiarism is False

    def test_rows_that_were_never_blank_are_unaffected_by_downgrade(self) -> None:
        """The false-positive direction, the same inversion ``0038``'s test needed.

        Seeding only a ``"missing"`` row would be vacuous: the rewrite sets the
        literal ``marker_source = 'missing'``, so such a row reads back
        ``"missing"`` under EVERY possible ``WHERE`` clause, including a broken
        one (``<> 'deterministic'`` would silently overwrite every ``"ai"`` and
        ``"dropped"`` row too). ``"deterministic"``, ``"ai"`` and ``"dropped"``
        are the values a broken ``WHERE`` would actually damage.
        """
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            seeded = {
                value: _seed_question_result(engine, marker_source=value)
                for value in ("missing", "deterministic", "ai", "dropped")
            }

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                rows = {
                    row.id: row.marker_source
                    for row in conn.execute(
                        sa.text("SELECT id, marker_source FROM question_results")
                    )
                }
            assert {value: rows[qr_id] for value, qr_id in seeded.items()} == {
                "missing": "missing",
                "deterministic": "deterministic",
                "ai": "ai",
                "dropped": "dropped",
            }
