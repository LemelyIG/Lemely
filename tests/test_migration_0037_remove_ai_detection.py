"""F4 acceptance (2a/2b/2c) + review findings: migration ``0037_remove_ai_detection``.

Four properties, each requiring the *real* migration to run (not
``Base.metadata.create_all``, which only reflects the current ORM state and
never executes a migration's data steps — see ``migrated_sessionmaker``'s own
docstring in ``tests/conftest.py``):

* 2a — schema round-trip: on an EMPTY database, ``upgrade`` then
  ``downgrade`` leaves the ``reviewreason`` enum members and
  ``review_queue`` columns exactly as they were before ``upgrade`` ran.
* 2b — one-way data rewrite on ``review_queue.reason``: a row seeded with
  ``reason = 'ai_detection_flag'`` is rewritten to ``'manual'`` on upgrade,
  with exactly one audit-log row per affected item; a subsequent
  ``downgrade`` does NOT restore ``ai_detection_flag`` on that row. Also
  covers the plural claim ("per affected item") with a two-row seed, and the
  false-positive direction: a row already ``'manual'`` before upgrade is not
  audit-logged.
* 2b (student-visible half, adversarial-review finding F-1) — the same
  one-way rewrite on ``question_results.review_reason``, the free-text
  column that renders directly on a student's own results page. Strips
  exactly the detector's ``"ai_detection (score 0.NN)"`` segment, whether it
  is the whole string or joined to other segments by ``" | "``, and turns an
  emptied string into ``NULL`` rather than ``""``.
* 2c — after upgrade, ``random_audit`` is a valid enum member and
  ``review_queue.is_audit`` defaults to ``false`` on every existing row.

Each test builds its own throwaway database (mirroring
``tests/conftest.py``'s ``migrated_sessionmaker``, but stopped at a specific
revision rather than always going to ``head``) because the round-trip and
one-way-rewrite properties both need control over *which* revisions run and
in what order, which the shared fixture (always ``upgrade head``) can't give.
"""

from __future__ import annotations

import os
import re
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

_PRE_MIGRATION_REVISION = "0036_upload_idempotency_key"
_MIGRATION_REVISION = "0037_remove_ai_detection"
_MIGRATION_FILE = (
    Path(__file__).resolve().parents[1]
    / "lemely"
    / "db"
    / "migrations"
    / "versions"
    / f"{_MIGRATION_REVISION}.py"
)


class TestLockTimeoutIsAlwaysReset:
    """review-closure ask: pin ``RESET lock_timeout``, since nothing behavioural
    can — a fresh connection to the same database already starts with
    whatever the server/role default is, whether or not the migration's own
    (now-closed) connection reset its session-level ``lock_timeout``, so no
    query issued after ``command.upgrade``/``command.downgrade`` returns can
    observe the leak this guards against. The only place this defect is
    visible is the migration's own source, in the one Postgres session both
    the offending ``SET`` and the fix's ``RESET`` share — so this asserts on
    that source directly, the same way a linter would, rather than pretending
    a runtime probe exists where none can.

    ``env.py`` runs every migration one ``alembic upgrade``/``downgrade``
    invocation applies in ONE shared transaction (``transaction_per_migration``
    unset — see the migration's own docstring), so a ``SET lock_timeout``
    with no matching ``RESET`` before ``upgrade()``/``downgrade()`` returns
    would silently keep applying to every later migration that same
    invocation runs afterward.
    """

    def test_upgrade_and_downgrade_each_reset_the_lock_timeout_they_set(self) -> None:
        source = _MIGRATION_FILE.read_text()
        upgrade_body, downgrade_body = self._split_upgrade_downgrade(source)
        for name, body in (("upgrade", upgrade_body), ("downgrade", downgrade_body)):
            # `"SET lock_timeout"` as a bare substring also matches inside
            # `"RESET lock_timeout"` (RE + SET lock_timeout) — requiring the
            # `= '...'` that only the actual SET statement has avoids double
            # counting the RESET line as a SET too.
            set_count = len(re.findall(r"SET lock_timeout = ", body))
            reset_count = len(re.findall(r"RESET lock_timeout", body))
            assert set_count >= 1, f"{name}() never sets lock_timeout at all"
            assert reset_count >= set_count, (
                f"{name}() sets lock_timeout {set_count} time(s) but only resets it "
                f"{reset_count} time(s) — a later migration in the same alembic "
                "invocation would inherit the leftover timeout"
            )
            # The RESET must actually come after the SET, not merely exist
            # somewhere in the function body (e.g. a RESET before the timeout
            # is even set would leave it leaked exactly the same way).
            set_pos = body.index("SET lock_timeout = ")
            reset_pos = body.rindex("RESET lock_timeout")
            assert reset_pos > set_pos, f"{name}()'s RESET must come after its SET"

    @staticmethod
    def _split_upgrade_downgrade(source: str) -> tuple[str, str]:
        upgrade_match = re.search(r"\ndef upgrade\(\).*?(?=\ndef downgrade\()", source, re.DOTALL)
        downgrade_match = re.search(r"\ndef downgrade\(\).*", source, re.DOTALL)
        assert upgrade_match is not None, "could not locate upgrade() in the migration source"
        assert downgrade_match is not None, "could not locate downgrade() in the migration source"
        return upgrade_match.group(0), downgrade_match.group(0)


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

    Mirrors ``tests/conftest.py``'s ``migrated_sessionmaker`` fixture — same
    env-var routing rationale (``lemely/db/migrations/env.py`` re-derives the
    URL from ``load_settings()``, so ``LEMELY_DATABASE__URL`` is what
    actually steers ``command.upgrade``/``command.downgrade``, not
    ``cfg.set_main_option``) — but yields the ``Config`` itself instead of
    always upgrading to ``head``, so callers can drive specific revisions.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig0037_{uuid.uuid4().hex[:12]}"
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
            sa.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :name"
            ),
            {"name": table_name},
        ).all()
    return {r[0] for r in rows}


def _table_exists(engine: Engine, table_name: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :name"),
                {"name": table_name},
            ).first()
        )


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


def _seed_review_queue_row(engine: Engine, *, reason: str) -> uuid.UUID:
    """Seed one user + attempt + a ``review_queue`` row with the given ``reason``.

    Raw SQL, not the ORM: at :data:`_PRE_MIGRATION_REVISION` the ORM's
    current model definitions (already post-F4) don't match the schema that
    revision actually produces (``ai_detection_flag`` still exists,
    ``is_audit`` does not) — the whole point of testing against the
    migration rather than ``Base.metadata``.
    """
    item_id = uuid.uuid4()
    with engine.begin() as conn:
        attempt_id = _seed_user_and_attempt(conn)
        conn.execute(
            sa.text(
                "INSERT INTO review_queue (id, attempt_id, reason) "
                "VALUES (:id, :attempt_id, :reason)"
            ),
            {"id": item_id, "attempt_id": attempt_id, "reason": reason},
        )
    return item_id


def _seed_question_result(engine: Engine, *, review_reason: str | None) -> uuid.UUID:
    """Seed one user + attempt + a ``question_results`` row carrying ``review_reason``."""
    qr_id = uuid.uuid4()
    with engine.begin() as conn:
        attempt_id = _seed_user_and_attempt(conn)
        conn.execute(
            sa.text(
                "INSERT INTO question_results "
                "(id, attempt_id, question_id, awarded_marks, maximum_marks, "
                " confidence_band, confidence_score, marker_source, review_reason) "
                "VALUES (:id, :attempt_id, '1', 1, 1, 'high', 0.95, 'ai', :review_reason)"
            ),
            {"id": qr_id, "attempt_id": attempt_id, "review_reason": review_reason},
        )
    return qr_id


def _audit_rows(engine: Engine, *, source_table: str) -> list[sa.RowMapping]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text(
                    "SELECT source_table, source_id, previous_value, new_value "
                    "FROM ai_detection_removal_audit_log WHERE source_table = :t "
                    "ORDER BY previous_value"
                ),
                {"t": source_table},
            )
            .mappings()
            .all()
        )


class TestSchemaRoundTrip:
    """2a: upgrade then downgrade on an empty DB leaves the schema identical."""

    def test_enum_members_restored(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _enum_members(engine, "reviewreason")

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _enum_members(engine, "reviewreason")
            assert during == {"low_confidence", "plagiarism_flag", "manual", "random_audit"}

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _enum_members(engine, "reviewreason")
            assert after == before

    def test_review_queue_columns_restored(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            before = _columns(engine, "review_queue")
            assert "is_audit" not in before

            command.upgrade(cfg, _MIGRATION_REVISION)
            during = _columns(engine, "review_queue")
            assert "is_audit" in during

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            after = _columns(engine, "review_queue")
            assert after == before

    def test_audit_log_table_dropped_on_downgrade(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _MIGRATION_REVISION)
            assert _table_exists(engine, "ai_detection_removal_audit_log")

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)
            assert not _table_exists(engine, "ai_detection_removal_audit_log")


class TestReviewQueueOneWayRewrite:
    """2b: ``review_queue.reason`` — upgrade rewrites ``ai_detection_flag`` to
    ``manual`` and logs exactly one audit entry per affected item; downgrade
    does not restore it (documented lossy step, see the migration's own
    docstring)."""

    def test_upgrade_rewrites_reason_and_writes_one_audit_entry(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            item_id = _seed_review_queue_row(engine, reason="ai_detection_flag")

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                reason = conn.execute(
                    sa.text("SELECT reason FROM review_queue WHERE id = :id"),
                    {"id": item_id},
                ).scalar_one()
                assert reason == "manual"

            audit_rows = _audit_rows(engine, source_table="review_queue")
            assert len(audit_rows) == 1
            assert audit_rows[0]["source_id"] == item_id
            assert audit_rows[0]["previous_value"] == "ai_detection_flag"
            assert audit_rows[0]["new_value"] == "manual"

    def test_multiple_affected_rows_each_get_their_own_audit_entry(self) -> None:
        """The plural claim ('one row per affected item') on more than one row."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            item_ids = {
                _seed_review_queue_row(engine, reason="ai_detection_flag") for _ in range(2)
            }

            command.upgrade(cfg, _MIGRATION_REVISION)

            audit_rows = _audit_rows(engine, source_table="review_queue")
            assert {r["source_id"] for r in audit_rows} == item_ids
            assert len(audit_rows) == 2

    def test_a_row_already_manual_is_not_audit_logged(self) -> None:
        """The false-positive direction of the WHERE clause: a row that was
        genuinely ``manual`` before this migration must not be touched or
        logged — only rows that actually held ``ai_detection_flag`` were."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            _seed_review_queue_row(engine, reason="manual")

            command.upgrade(cfg, _MIGRATION_REVISION)

            assert _audit_rows(engine, source_table="review_queue") == []

    def test_downgrade_does_not_restore_ai_detection_flag(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            item_id = _seed_review_queue_row(engine, reason="ai_detection_flag")
            command.upgrade(cfg, _MIGRATION_REVISION)

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                reason = conn.execute(
                    sa.text("SELECT reason FROM review_queue WHERE id = :id"),
                    {"id": item_id},
                ).scalar_one()
                # Lossy by design (documented in the migration): the row stays
                # 'manual' — it is NOT restored to 'ai_detection_flag', even
                # though that enum member itself is back after downgrade.
                assert reason == "manual"


class TestQuestionResultReviewReasonOneWayRewrite:
    """Adversarial-review finding F-1: the student-visible free-text column.

    Pre-F4, ``apply_integrity_checks`` appended a literal
    ``"ai_detection (score 0.NN)"`` segment onto
    ``CorrectedQuestion.review_reason``, persisted verbatim by
    ``AttemptRepository`` into ``question_results.review_reason`` — a column
    rendered directly on the student's own results page
    (``PaperResult.tsx``). The enum rewrite above never touched this column;
    these tests are what closes that gap.
    """

    def test_sole_segment_becomes_null(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, review_reason="ai_detection (score 0.90)")

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason is None

    def test_trailing_segment_is_stripped_leaving_the_rest_intact(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine,
                review_reason="plagiarism (score 0.95) | ai_detection (score 0.90)",
            )

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason == "plagiarism (score 0.95)"

    def test_three_segment_reason_keeps_the_non_detector_segments(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine,
                review_reason=(
                    "confidence 0.50 below review threshold 0.90 | "
                    "plagiarism (score 0.95) | ai_detection (score 0.90)"
                ),
            )

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason == (
                    "confidence 0.50 below review threshold 0.90 | plagiarism (score 0.95)"
                )

    def test_middle_segment_is_stripped(self) -> None:
        """Closure-review finding: an earlier anchored-regex version of this
        migration only matched a segment at the very start or very end of the
        ' | '-joined string, so a detector segment in the MIDDLE of three
        survived the rewrite completely — while still being logged as
        rewritten in the audit table (the false-audit-entry half of the same
        defect, covered by ``test_a_middle_segment_does_not_produce_a_lying_audit_entry``
        below). This is the regression test: three segments, detector in the
        middle position, none of the earlier tests in this file exercise it
        because ``test_three_segment_reason_keeps_the_non_detector_segments``
        puts the detector last."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine,
                review_reason=(
                    "plagiarism (score 0.95) | ai_detection (score 0.90) | missing answer"
                ),
            )

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason == "plagiarism (score 0.95) | missing answer"

    def test_a_middle_segment_does_not_produce_a_lying_audit_entry(self) -> None:
        """The audit-log half of the same defect: the anchored-regex version
        computed the audit `new_value` with the identical (broken) expression
        used for the `UPDATE`, so a middle segment that survived the rewrite
        ALSO produced an audit row whose `previous_value` equalled its
        `new_value` — an entry claiming a rewrite that never happened, in the
        table whose entire purpose is to be the record of what changed."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            original = "plagiarism (score 0.95) | ai_detection (score 0.90) | missing answer"
            qr_id = _seed_question_result(engine, review_reason=original)

            command.upgrade(cfg, _MIGRATION_REVISION)

            audit_rows = _audit_rows(engine, source_table="question_results")
            row = next(r for r in audit_rows if r["source_id"] == qr_id)
            assert row["previous_value"] == original
            assert row["new_value"] == "plagiarism (score 0.95) | missing answer"
            assert row["new_value"] != row["previous_value"]

    def test_repeated_segment_is_fully_removed(self) -> None:
        """A second finding from the same closure review: the anchored regex
        also left a repeated segment's second copy behind (it consumes at
        most one match). Two detector segments, both must go, result is NULL
        (both segments removed, nothing left)."""
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine,
                review_reason="ai_detection (score 0.90) | ai_detection (score 0.85)",
            )

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason is None

    def test_a_reason_without_the_detector_segment_is_untouched(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, review_reason="plagiarism (score 0.95)")

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason == "plagiarism (score 0.95)"
            assert _audit_rows(engine, source_table="question_results") == []

    def test_upgrade_writes_one_audit_entry_with_the_pre_strip_text(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(
                engine,
                review_reason="plagiarism (score 0.95) | ai_detection (score 0.90)",
            )

            command.upgrade(cfg, _MIGRATION_REVISION)

            audit_rows = _audit_rows(engine, source_table="question_results")
            assert len(audit_rows) == 1
            assert audit_rows[0]["source_id"] == qr_id
            assert audit_rows[0]["previous_value"] == (
                "plagiarism (score 0.95) | ai_detection (score 0.90)"
            )
            assert audit_rows[0]["new_value"] == "plagiarism (score 0.95)"

    def test_downgrade_does_not_restore_the_stripped_segment(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            qr_id = _seed_question_result(engine, review_reason="ai_detection (score 0.90)")
            command.upgrade(cfg, _MIGRATION_REVISION)

            command.downgrade(cfg, _PRE_MIGRATION_REVISION)

            with engine.connect() as conn:
                review_reason = conn.execute(
                    sa.text("SELECT review_reason FROM question_results WHERE id = :id"),
                    {"id": qr_id},
                ).scalar_one()
                assert review_reason is None


class TestRandomAuditAndIsAudit:
    """2c: after upgrade, ``random_audit`` exists and ``is_audit`` defaults to
    false on existing rows."""

    def test_random_audit_is_a_usable_enum_member(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            with engine.begin() as conn:
                attempt_id = _seed_user_and_attempt(conn)

            command.upgrade(cfg, _MIGRATION_REVISION)

            new_item_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO review_queue (id, attempt_id, reason) "
                        "VALUES (:id, :attempt_id, 'random_audit')"
                    ),
                    {"id": new_item_id, "attempt_id": attempt_id},
                )
            with engine.connect() as conn:
                reason, is_audit = conn.execute(
                    sa.text("SELECT reason, is_audit FROM review_queue WHERE id = :id"),
                    {"id": new_item_id},
                ).one()
                assert reason == "random_audit"
                # No explicit value given for is_audit — its own column
                # default applies (False), not the sampler's intent, since
                # N2 (the sampler) is not implemented by this migration.
                assert is_audit is False

    def test_is_audit_defaults_false_on_pre_existing_rows(self) -> None:
        with _throwaway_db() as (cfg, engine):
            command.upgrade(cfg, _PRE_MIGRATION_REVISION)
            item_id = _seed_review_queue_row(engine, reason="ai_detection_flag")

            command.upgrade(cfg, _MIGRATION_REVISION)

            with engine.connect() as conn:
                is_audit = conn.execute(
                    sa.text("SELECT is_audit FROM review_queue WHERE id = :id"),
                    {"id": item_id},
                ).scalar_one()
                assert is_audit is False
