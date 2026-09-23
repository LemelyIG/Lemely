"""US-045 acceptance: migration ``0041_point_verdict_columns``.

The migration adds three columns to ``question_result_points`` so I6's
per-point verdicts (``CorrectedQuestion.point_verdicts``) can be persisted:
``verdict`` (text, nullable), ``evidence_span`` (text, not-null, default
``''``) and ``ecf_applied`` (bool, not-null, default ``false``).

Properties, each requiring the *real* migration to run (not
``Base.metadata.create_all``, which only reflects the current ORM state and
never executes a migration's own ``server_default`` -- see
``tests/test_migration_0040_marker_source_blank.py``'s docstring, whose
structure and throwaway-database helper this file follows):

* Schema round-trip on an EMPTY database: ``upgrade`` then ``downgrade``
  leaves ``question_result_points`` with exactly the pre-migration column
  set -- the three new columns gone, and every pre-existing column
  unchanged in type, nullability and server default.
* After ``upgrade``, a row inserted WITHOUT ``evidence_span``/``ecf_applied``
  gets ``''``/``false`` from the migration's own ``server_default`` -- the
  half a ``create_all``-based test could never see, since the ORM model
  would supply its own Python-side default regardless of what the DDL says.
* ``verdict`` accepts ``NULL`` and round-trips each of ``"awarded"``,
  ``"withheld"`` and ``"unverifiable"`` -- it is a plain ``TEXT`` column
  (0041's own docstring: stored loosely, not a native enum), so nothing
  constrains it to those three values at the DB layer, but the values I6
  actually writes must survive unchanged.
* ``downgrade`` does not fail on a table holding rows that carry verdict
  data -- and per 0041's own docstring, this is a LOSSY round trip: the
  columns and the data in them are dropped, with no backfill onto any
  surviving column (unlike ``0040_marker_source_blank``'s ``"blank"``,
  which rewrites onto ``marker_source`` before the enum member is
  removed). The downgrade test asserts exactly that documented behaviour,
  not a backfill that does not exist.
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

_PRE_MIGRATION_REVISION = "0040_marker_source_blank"
_MIGRATION_REVISION = "0041_point_verdict_columns"
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

    Same env-var routing rationale as the ``0040``/``0038`` migration tests:
    ``lemely/db/migrations/env.py`` re-derives the URL from ``load_settings()``,
    so ``LEMELY_DATABASE__URL`` is what actually steers
    ``command.upgrade``/``command.downgrade``, not ``cfg.set_main_option``.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig0041_{uuid.uuid4().hex[:12]}"
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


def _seed_question_result(engine: Engine) -> uuid.UUID:
    """Seed one user + attempt + a ``question_results`` row.

    The row's own values are irrelevant to this migration; it exists only to
    satisfy ``question_result_points.question_result_id``'s foreign key.
    """
    qr_id = uuid.uuid4()
    with engine.begin() as conn:
        attempt_id = _seed_user_and_attempt(conn)
        conn.execute(
            sa.text(
                "INSERT INTO question_results "
                "(id, attempt_id, question_id, awarded_marks, maximum_marks, "
                " confidence_band, confidence_score, marker_source, needs_teacher_review) "
                "VALUES (:id, :attempt_id, '1', 1, 1, 'high', 0.95, "
                " CAST('ai' AS markersource), false)"
            ),
            {"id": qr_id, "attempt_id": attempt_id},
        )
    return qr_id


class TestSchemaRoundTrip:
    """Upgrade then downgrade on an empty DB leaves the schema identical."""

    def test_the_three_columns_are_added_and_removed_in_full(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _column_shapes(engine, "question_result_points")
            assert not {"verdict", "evidence_span", "ecf_applied"} & set(before)

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _column_shapes(engine, "question_result_points")
            added = set(during) - set(before)
            assert added == {"verdict", "evidence_span", "ecf_applied"}
            assert during["verdict"] == ("text", "YES", None)
            assert during["evidence_span"][0] == "text"
            assert during["evidence_span"][1] == "NO"
            assert during["evidence_span"][2] is not None and "''" in during["evidence_span"][2]
            assert during["ecf_applied"][0] == "boolean"
            assert during["ecf_applied"][1] == "NO"
            assert during["ecf_applied"][2] is not None and "false" in during["ecf_applied"][2]
            # Every pre-existing column is untouched by the add.
            assert {k: v for k, v in during.items() if k in before} == before

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _column_shapes(engine, "question_result_points")
            # Type, nullability AND default, not just the name: the table
            # must come back exactly as it was before this migration.
            assert after == before


class TestServerDefaultsApplyOnInsert:
    """A row inserted without the two not-null columns gets the migration's
    own ``server_default`` -- not an ORM-side default, since this INSERT
    never goes through the ORM at all."""

    def test_evidence_span_and_ecf_applied_default_at_the_database_layer(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine)
            point_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO question_result_points "
                        "(id, question_result_id, mark_point_id, ordinal, tariff, "
                        " point_text, awarded) "
                        "VALUES (:id, :qr_id, 'p1', 0, 1, 'method step', true)"
                    ),
                    {"id": point_id, "qr_id": qr_id},
                )

            with engine.connect() as conn:
                verdict, evidence_span, ecf_applied = conn.execute(
                    sa.text(
                        "SELECT verdict, evidence_span, ecf_applied "
                        "FROM question_result_points WHERE id = :id"
                    ),
                    {"id": point_id},
                ).one()
            assert verdict is None
            assert evidence_span == ""
            assert ecf_applied is False


class TestVerdictColumnRoundTrip:
    """``verdict`` is plain ``TEXT`` (0041's own docstring: stored loosely, no
    native enum), but every value I6 actually writes must survive unchanged,
    and ``NULL`` (the legacy-path case) must be a valid state too."""

    @pytest.mark.parametrize("verdict", ["awarded", "withheld", "unverifiable", None])
    def test_verdict_round_trips(self, verdict: str | None) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine)
            point_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO question_result_points "
                        "(id, question_result_id, mark_point_id, ordinal, tariff, "
                        " point_text, awarded, verdict) "
                        "VALUES (:id, :qr_id, 'p1', 0, 1, 'method step', true, :verdict)"
                    ),
                    {"id": point_id, "qr_id": qr_id, "verdict": verdict},
                )

            with engine.connect() as conn:
                (stored,) = conn.execute(
                    sa.text("SELECT verdict FROM question_result_points WHERE id = :id"),
                    {"id": point_id},
                ).one()
            assert stored == verdict


class TestDowngradeIsLossy:
    """``downgrade`` drops all three columns unconditionally -- it does not,
    and per 0041's own docstring cannot, preserve a row's verdict data by
    backfilling it onto any surviving column (unlike ``"blank"`` in
    ``0040_marker_source_blank``, which rewrites onto ``marker_source``
    before its enum member is removed). This test asserts that documented
    lossy behaviour, not a backfill that was never built.
    """

    def test_downgrade_succeeds_and_drops_verdict_data_with_the_columns(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            qr_id = _seed_question_result(engine)
            point_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO question_result_points "
                        "(id, question_result_id, mark_point_id, ordinal, tariff, "
                        " point_text, awarded, verdict, evidence_span, ecf_applied) "
                        "VALUES (:id, :qr_id, 'p1', 0, 1, 'method step', true, "
                        " 'awarded', '12.5 m/s', true)"
                    ),
                    {"id": point_id, "qr_id": qr_id},
                )

            # Must not raise: dropping a column with data in it is exactly
            # what this downgrade does.
            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            columns = _column_shapes(engine, "question_result_points")
            assert not {"verdict", "evidence_span", "ecf_applied"} & set(columns)

            # The row itself survives the downgrade (only the three columns
            # and their data are gone, not the point row).
            with engine.connect() as conn:
                (mark_point_id,) = conn.execute(
                    sa.text("SELECT mark_point_id FROM question_result_points WHERE id = :id"),
                    {"id": point_id},
                ).one()
            assert mark_point_id == "p1"
