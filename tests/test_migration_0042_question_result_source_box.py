"""E acceptance: migration ``0042_question_result_source_box``.

The migration adds five columns to ``question_results`` so extraction's
``CorrectedQuestion.source_box`` (Task 1) can be persisted for the teacher
crop route (Task 4): ``source_box_page``, ``source_box_ymin``,
``source_box_xmin``, ``source_box_ymax`` and ``source_box_xmax``, all
``Integer`` and nullable.

Properties, each requiring the *real* migration to run (not
``Base.metadata.create_all``, which only reflects the current ORM state and
never executes a migration's own CHECK constraints -- see
``tests/test_migration_0041_point_verdict_columns.py``'s docstring, whose
structure and throwaway-database helper this file follows):

* Schema round-trip on an EMPTY database: ``upgrade`` then ``downgrade``
  leaves ``question_results`` with exactly the pre-migration column set --
  the five new columns gone, and every pre-existing column unchanged in
  type, nullability and server default.
* A raw, non-ORM INSERT of a valid box (``page=2``, ``[100, 200, 300,
  400]``) round-trips unchanged.
* A raw INSERT with a coordinate of ``1001`` is rejected by the database --
  ``ck_question_results_source_box_range``.
* A raw INSERT with ``ymax <= ymin`` is rejected --
  ``ck_question_results_source_box_positive_area``.
* A raw INSERT with ``source_box_page`` set but every coordinate ``NULL`` is
  rejected -- ``ck_question_results_source_box_all_or_none``.
* ``downgrade`` removes all five columns and all four CHECK constraints.

Points 3 to 5 are the entire reason for five explicit columns over a jsonb
blob: a jsonb blob has no CHECK constraint to reject a degenerate box before
it reaches the crop route. Each is asserted by catching the database's own
integrity error, not by inspecting constraint names.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from lemely.runtime.config import DatabaseSettings

_PRE_MIGRATION_REVISION = "0041_point_verdict_columns"
_MIGRATION_REVISION = "0042_question_result_source_box"

_COLUMNS = (
    "source_box_page",
    "source_box_ymin",
    "source_box_xmin",
    "source_box_ymax",
    "source_box_xmax",
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

    Same env-var routing rationale as the ``0041``/``0040``/``0038`` migration
    tests: ``lemely/db/migrations/env.py`` re-derives the URL from
    ``load_settings()``, so ``LEMELY_DATABASE__URL`` is what actually steers
    ``command.upgrade``/``command.downgrade``, not ``cfg.set_main_option``.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig0042_{uuid.uuid4().hex[:12]}"
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


def _column_shapes(engine: Engine, table_name: str) -> dict[str, tuple[str, str, str | None]]:
    """Every column's name, type, nullability and default.

    Names alone would let ``downgrade`` re-add a dropped column with the
    wrong nullability or no default and still pass.
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


def _source_box_check_constraint_count(engine: Engine, table_name: str) -> int:
    """Count CHECK constraints on ``table_name`` mentioning a ``source_box_*`` column.

    Not by name: ``op.create_check_constraint`` resolves constraint names
    through ``Base.metadata``'s naming convention (``lemely/db/base.py``),
    which -- given a name that already starts with ``ck_<table>_`` -- prefixes
    it again and then hash-truncates the result to fit Postgres's 63-byte
    identifier limit (pre-existing behaviour, also visible on
    ``component_thresholds``'s ``0026`` constraint). The constraint's
    *definition*, not its stored name, is what this migration's contract is
    about.
    """
    with engine.connect() as conn:
        (count,) = conn.execute(
            sa.text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%source_box%'"
            ),
            {"table": table_name},
        ).one()
    return int(count)


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


def _insert_question_result(
    engine: Engine,
    *,
    page: int | None,
    ymin: int | None,
    xmin: int | None,
    ymax: int | None,
    xmax: int | None,
) -> uuid.UUID:
    qr_id = uuid.uuid4()
    with engine.begin() as conn:
        attempt_id = _seed_user_and_attempt(conn)
        conn.execute(
            sa.text(
                "INSERT INTO question_results "
                "(id, attempt_id, question_id, awarded_marks, maximum_marks, "
                " confidence_band, confidence_score, marker_source, needs_teacher_review, "
                " source_box_page, source_box_ymin, source_box_xmin, source_box_ymax, "
                " source_box_xmax) "
                "VALUES (:id, :attempt_id, '1', 1, 1, 'high', 0.95, "
                " CAST('ai' AS markersource), false, "
                " :page, :ymin, :xmin, :ymax, :xmax)"
            ),
            {
                "id": qr_id,
                "attempt_id": attempt_id,
                "page": page,
                "ymin": ymin,
                "xmin": xmin,
                "ymax": ymax,
                "xmax": xmax,
            },
        )
    return qr_id


class TestSchemaRoundTrip:
    """Upgrade then downgrade on an empty DB leaves the schema identical."""

    def test_the_five_columns_and_constraints_are_added_and_removed_in_full(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _column_shapes(engine, "question_results")
            assert not set(_COLUMNS) & set(before)

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _column_shapes(engine, "question_results")
            added = set(during) - set(before)
            assert added == set(_COLUMNS)
            for name in _COLUMNS:
                assert during[name] == ("integer", "YES", None)
            # Every pre-existing column is untouched by the add.
            assert {k: v for k, v in during.items() if k in before} == before

            assert _source_box_check_constraint_count(engine, "question_results") == 4

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _column_shapes(engine, "question_results")
            assert after == before
            assert _source_box_check_constraint_count(engine, "question_results") == 0


class TestValidBoxRoundTrips:
    def test_a_valid_box_round_trips_unchanged(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _insert_question_result(engine, page=2, ymin=100, xmin=200, ymax=300, xmax=400)

            with engine.connect() as conn:
                row = conn.execute(
                    sa.text(
                        "SELECT source_box_page, source_box_ymin, source_box_xmin, "
                        "source_box_ymax, source_box_xmax "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert tuple(row) == (2, 100, 200, 300, 400)

    def test_all_null_is_a_valid_row(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _insert_question_result(
                engine, page=None, ymin=None, xmin=None, ymax=None, xmax=None
            )
            with engine.connect() as conn:
                row = conn.execute(
                    sa.text(
                        "SELECT source_box_page, source_box_ymin, source_box_xmin, "
                        "source_box_ymax, source_box_xmax "
                        "FROM question_results WHERE id = :id"
                    ),
                    {"id": qr_id},
                ).one()
            assert tuple(row) == (None, None, None, None, None)


class TestConstraintsRejectDegenerateBoxes:
    """Each of these is only possible because the columns are explicit
    integers with CHECK constraints -- a jsonb blob would let all three
    through to the crop route."""

    def test_a_coordinate_above_1000_is_rejected(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            with pytest.raises(IntegrityError):
                _insert_question_result(engine, page=0, ymin=100, xmin=200, ymax=300, xmax=1001)

    def test_ymax_not_greater_than_ymin_is_rejected(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            with pytest.raises(IntegrityError):
                _insert_question_result(engine, page=0, ymin=300, xmin=200, ymax=300, xmax=400)

    def test_a_half_written_box_is_rejected(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            with pytest.raises(IntegrityError):
                _insert_question_result(engine, page=1, ymin=None, xmin=None, ymax=None, xmax=None)
