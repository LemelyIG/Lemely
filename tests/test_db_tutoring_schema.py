"""DB-level guards for the tutoring schema (SPEC §a.2-§a.4, §e.4 "Constraint tests").

Two databases per module, built two ways:

* ``create_all``: ``Base.metadata.create_all`` on a fresh database, the way
  about 88 test files build theirs (SPEC §a.4, F2). This is what proves the
  ORM in ``lemely/db/models/tutoring.py`` and its ``btree_gist`` listener.
* ``migrated``: ``alembic upgrade head`` (``0044``-``0050``).

Every behavioural constraint test runs against **both** (the ``schema_engine``
fixture is parametrised), and
:func:`test_create_all_and_migrations_build_identical_tutoring_schemas` compares
the two catalogues object by object, because ``alembic check`` cannot see
exclusion constraints, computed columns, partial predicates or CHECK text
(SPEC §a.4, F20).

Each test works inside one transaction that is rolled back at the end, with a
savepoint around every statement expected to fail, so the module databases stay
empty between tests.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

import lemely.db.models.tutoring as tutoring_models
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import BookingState
from lemely.db.tutoring_predicates import EFFECTIVE_STATE_SQL
from lemely.runtime.config import DatabaseSettings
from tests.test_migration_tutoring_enums import (
    extension_installed,
    spec_enum_types,
    spec_names_for,
    spec_new_notification_types,
    spec_tutoring_tables,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

import_all_models()

TUTORING_TABLES = spec_tutoring_tables()
EXCLUSIONS = {
    "excl_tutor_availability_rules_no_overlap",
    "excl_tutor_bookings_tutor_slot",
    "excl_tutor_bookings_student_slot",
}
LINK = "https://meet.google.com/abc-defg-hij"


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------


def _server_url() -> sa.URL:
    base = make_url(DatabaseSettings().url)
    server = base.set(database="postgres")
    probe = create_engine(server)
    try:
        with probe.connect():
            pass
    except OperationalError:
        pytest.skip("local Postgres not reachable")
    finally:
        probe.dispose()
    return base


@contextmanager
def _fresh_database() -> Iterator[sa.URL]:
    base = _server_url()
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def create_all_engine() -> Iterator[sa.Engine]:
    with _fresh_database() as url:
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[sa.Engine]:
    """``alembic upgrade head`` on a fresh database (same mechanism as conftest's fixture)."""
    with _fresh_database() as url:
        rendered = url.render_as_string(hide_password=False)
        previous = os.environ.get("LEMELY_DATABASE__URL")
        os.environ["LEMELY_DATABASE__URL"] = rendered
        try:
            command.upgrade(Config("alembic.ini"), "head")
        finally:
            if previous is None:
                os.environ.pop("LEMELY_DATABASE__URL", None)
            else:
                os.environ["LEMELY_DATABASE__URL"] = previous
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture(scope="module", params=["create_all", "migrated"])
def schema_engine(request: pytest.FixtureRequest) -> sa.Engine:
    return request.getfixturevalue(f"{request.param}_engine")


@contextmanager
def _rolled_back(engine: sa.Engine) -> Iterator[sa.Connection]:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            yield conn
        finally:
            transaction.rollback()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _insert(conn: sa.Connection, table: str, values: dict[str, object]) -> None:
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    statement = f"INSERT INTO {table} ({columns}) VALUES ({binds})"  # noqa: S608 - test-owned names
    conn.execute(sa.text(statement), values)


def _violation(
    conn: sa.Connection,
    statement: Callable[[], object],
    *,
    sqlstate: str,
    constraint: str,
) -> None:
    """Run ``statement`` in a savepoint; it must fail on exactly ``constraint``."""
    with pytest.raises(IntegrityError) as excinfo, conn.begin_nested():
        statement()
    orig = excinfo.value.orig
    assert (orig.sqlstate, orig.diag.constraint_name) == (sqlstate, constraint)


def _insert_violates(
    conn: sa.Connection, table: str, values: dict[str, object], *, sqlstate: str, constraint: str
) -> None:
    _violation(conn, lambda: _insert(conn, table, values), sqlstate=sqlstate, constraint=constraint)


def _insert_ok(conn: sa.Connection, table: str, values: dict[str, object]) -> None:
    with conn.begin_nested():
        _insert(conn, table, values)


@dataclass(frozen=True)
class World:
    """Users, a subject and two tutor profiles whose ids differ from their users' ids."""

    student: uuid.UUID
    student2: uuid.UUID
    parent: uuid.UUID
    tutor_user: uuid.UUID
    tutor_user2: uuid.UUID
    admin: uuid.UUID
    subject: str
    profile: uuid.UUID
    profile2: uuid.UUID


def _user(conn: sa.Connection, role: str) -> uuid.UUID:
    uid = uuid.uuid4()
    _insert(conn, "users", {"id": uid, "email": f"{uid}@example.com", "role": role})
    return uid


def _profile_row(user_id: uuid.UUID) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "public_first_name": "Sara",
        "headline": "IGCSE Mathematics",
        "offers_virtual": True,
        "area_code": "cairo",
    }


def _world(conn: sa.Connection) -> World:
    student, student2 = _user(conn, "student"), _user(conn, "student")
    parent, admin = _user(conn, "parent"), _user(conn, "platform_admin")
    tutor_user, tutor_user2 = _user(conn, "teacher"), _user(conn, "teacher")
    subject = f"T{uuid.uuid4().hex[:7]}"
    _insert(conn, "subjects", {"code": subject, "name": "Mathematics"})
    profile, profile2 = uuid.uuid4(), uuid.uuid4()
    _insert(conn, "tutor_profiles", _profile_row(tutor_user) | {"id": profile})
    _insert(conn, "tutor_profiles", _profile_row(tutor_user2) | {"id": profile2})
    world = World(
        student=student,
        student2=student2,
        parent=parent,
        tutor_user=tutor_user,
        tutor_user2=tutor_user2,
        admin=admin,
        subject=subject,
        profile=profile,
        profile2=profile2,
    )
    assert {world.profile, world.profile2}.isdisjoint({world.tutor_user, world.tutor_user2})
    return world


#: Far from any boundary: constraint tests never depend on the clock.
BASE = (datetime.now(UTC) + timedelta(days=10)).replace(minute=0, second=0, microsecond=0)


def _booking_row(
    w: World,
    *,
    profile: uuid.UUID | None = None,
    student: uuid.UUID | None = None,
    start: datetime = BASE,
    minutes: int = 60,
    **extra: object,
) -> dict[str, object]:
    student = student or w.student
    return {
        "id": uuid.uuid4(),
        "tutor_profile_id": profile or w.profile,
        "student_id": student,
        "requested_by_user_id": student,
        "requested_by_party": "student",
        "subject_code": w.subject,
        "mode": "virtual",
        "starts_at": start,
        "ends_at": start + timedelta(minutes=minutes),
        "state": "requested",
    } | extra


def _booking(conn: sa.Connection, w: World, **kwargs) -> uuid.UUID:
    row = _booking_row(w, **kwargs)
    _insert(conn, "tutor_bookings", row)
    return row["id"]


def _review(conn: sa.Connection, w: World, booking: uuid.UUID) -> uuid.UUID:
    rid = uuid.uuid4()
    _insert(
        conn,
        "tutor_reviews",
        {
            "id": rid,
            "booking_id": booking,
            "tutor_profile_id": w.profile,
            "student_id": w.student,
            "stars": 5,
            "text_state": "none",
        },
    )
    return rid


# ---------------------------------------------------------------------------
# btree_gist and create_all (SPEC §a.4, F2)
# ---------------------------------------------------------------------------


def test_create_all_on_fresh_database_installs_btree_gist() -> None:
    with _fresh_database() as url:
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                # Non-vacuity: the fresh database really starts without it.
                assert not extension_installed(conn, "btree_gist")
            Base.metadata.create_all(engine)
            with engine.connect() as conn:
                assert extension_installed(conn, "btree_gist")
                exclusions = set(
                    conn.execute(
                        sa.text("SELECT conname FROM pg_constraint WHERE contype = 'x'")
                    ).scalars()
                )
        finally:
            engine.dispose()
    assert exclusions == EXCLUSIONS


def test_orm_registers_every_spec_table() -> None:
    orm_tables = {getattr(tutoring_models, name).__tablename__ for name in tutoring_models.__all__}
    assert orm_tables == set(TUTORING_TABLES)
    assert len(orm_tables) == 17


# ---------------------------------------------------------------------------
# ORM and migrations agree (SPEC §a.4 F20: alembic check cannot see these)
# ---------------------------------------------------------------------------


def _catalogue(engine: sa.Engine) -> dict[str, set[tuple[object, ...]]]:
    tables = list(TUTORING_TABLES)
    with engine.connect() as conn:
        columns = conn.execute(
            sa.text(
                "SELECT table_name, column_name, data_type, udt_name, character_maximum_length, "
                "numeric_precision, numeric_scale, is_nullable, column_default, is_generated, "
                "generation_expression FROM information_schema.columns "
                "WHERE table_schema = 'public' AND (table_name = ANY(:tables) "
                "OR (table_name = 'notification_preferences' AND column_name = ANY(:toggles)))"
            ),
            {"tables": tables, "toggles": list(spec_new_notification_types())},
        ).all()
        constraints = conn.execute(
            sa.text(
                "SELECT t.relname, c.conname, c.contype, pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'public' AND t.relname = ANY(:tables)"
            ),
            {"tables": tables},
        ).all()
        indexes = conn.execute(
            sa.text(
                "SELECT tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = ANY(:tables)"
            ),
            {"tables": tables},
        ).all()
        enums = conn.execute(
            sa.text(
                "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)::text "
                "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                "WHERE t.typname = ANY(:types) GROUP BY t.typname"
            ),
            {"types": list(spec_enum_types())},
        ).all()
    return {
        "columns": {tuple(row) for row in columns},
        "constraints": {tuple(row) for row in constraints},
        "indexes": {tuple(row) for row in indexes},
        "enums": {tuple(row) for row in enums},
    }


def test_create_all_and_migrations_build_identical_tutoring_schemas(
    create_all_engine: sa.Engine, migrated_engine: sa.Engine
) -> None:
    orm = _catalogue(create_all_engine)
    migrated = _catalogue(migrated_engine)
    # Non-vacuity: every table, the 8 toggles and the 16 types are in both.
    assert {row[0] for row in orm["columns"]} >= set(TUTORING_TABLES)
    assert len(orm["enums"]) == len(spec_enum_types()) == 16
    assert len(orm["indexes"]) >= len([n for n in spec_names_for(TUTORING_TABLES) if "ix_" in n])
    for kind in ("columns", "constraints", "indexes", "enums"):
        only_orm = sorted(orm[kind] - migrated[kind], key=str)
        only_migrated = sorted(migrated[kind] - orm[kind], key=str)
        assert (only_orm, only_migrated) == ([], []), kind


# ---------------------------------------------------------------------------
# Exclusion and uniqueness (SPEC §a.4; verified 2026-10-25 against the local stack)
# ---------------------------------------------------------------------------


def test_overlapping_active_tutor_slot_rejected_23p01(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _booking(conn, w, state="accepted", accepted_at=BASE - timedelta(days=1), meeting_link=LINK)
        _insert_violates(
            conn,
            "tutor_bookings",
            _booking_row(w, student=w.student2, start=BASE + timedelta(minutes=30)),
            sqlstate="23P01",
            constraint="excl_tutor_bookings_tutor_slot",
        )


def test_overlapping_student_slot_rejected_23p01(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _booking(conn, w)
        _insert_violates(
            conn,
            "tutor_bookings",
            _booking_row(w, profile=w.profile2, start=BASE + timedelta(minutes=30)),
            sqlstate="23P01",
            constraint="excl_tutor_bookings_student_slot",
        )


def test_second_pending_same_pair_rejected_23505(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        first = _booking(conn, w)
        later = BASE + timedelta(days=1)
        _insert_violates(
            conn,
            "tutor_bookings",
            _booking_row(w, start=later),
            sqlstate="23505",
            constraint="uq_tutor_bookings_one_pending",
        )
        # Only *pending* rows are limited: once the first is accepted, a new request fits.
        conn.execute(
            sa.text(
                "UPDATE tutor_bookings SET state = 'accepted', accepted_at = now(), "
                "meeting_link = :link WHERE id = :id"
            ),
            {"id": first, "link": LINK},
        )
        _insert_ok(conn, "tutor_bookings", _booking_row(w, start=later))


def test_adjacent_slots_accepted(schema_engine: sa.Engine) -> None:
    """``[)`` ranges: a session may start exactly when the previous one ends."""
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _booking(conn, w)
        _insert_ok(
            conn,
            "tutor_bookings",
            _booking_row(w, student=w.student2, start=BASE + timedelta(hours=1)),
        )
        _insert_ok(
            conn,
            "tutor_bookings",
            _booking_row(w, profile=w.profile2, start=BASE + timedelta(hours=1)),
        )


@pytest.mark.parametrize(
    ("state", "columns"),
    [
        ("cancelled", "cancelled_at = now(), cancelled_by_party = 'student'"),
        ("declined", "declined_at = now()"),
    ],
)
def test_cancelled_row_frees_slot(schema_engine: sa.Engine, state: str, columns: str) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        first = _booking(conn, w)
        overlapping = _booking_row(w, student=w.student2, start=BASE + timedelta(minutes=30))
        _insert_violates(
            conn,
            "tutor_bookings",
            overlapping,
            sqlstate="23P01",
            constraint="excl_tutor_bookings_tutor_slot",
        )
        conn.execute(
            sa.text(f"UPDATE tutor_bookings SET state = '{state}', {columns} WHERE id = :id"),  # noqa: S608 - parametrize literals
            {"id": first},
        )
        _insert_ok(conn, "tutor_bookings", overlapping)


def test_availability_rules_overlap_rejected(schema_engine: sa.Engine) -> None:
    def rule(profile: uuid.UUID, day: int, start: int, end: int) -> dict[str, object]:
        return {
            "id": uuid.uuid4(),
            "tutor_profile_id": profile,
            "iso_weekday": day,
            "start_minute": start,
            "end_minute": end,
        }

    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _insert(conn, "tutor_availability_rules", rule(w.profile, 1, 600, 720))
        _insert_violates(
            conn,
            "tutor_availability_rules",
            rule(w.profile, 1, 690, 750),
            sqlstate="23P01",
            constraint="excl_tutor_availability_rules_no_overlap",
        )
        _insert_ok(conn, "tutor_availability_rules", rule(w.profile, 1, 720, 780))  # adjacent
        _insert_ok(conn, "tutor_availability_rules", rule(w.profile, 2, 600, 720))  # other day
        _insert_ok(conn, "tutor_availability_rules", rule(w.profile2, 1, 600, 720))  # other tutor


def test_one_live_grant_per_pair(schema_engine: sa.Engine) -> None:
    def grant(w: World, profile: uuid.UUID) -> dict[str, object]:
        return {"id": uuid.uuid4(), "student_id": w.student, "tutor_profile_id": profile}

    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        first = grant(w, w.profile)
        _insert(conn, "tutor_data_grants", first)
        _insert_violates(
            conn,
            "tutor_data_grants",
            grant(w, w.profile),
            sqlstate="23505",
            constraint="uq_tutor_data_grants_live",
        )
        _insert_ok(conn, "tutor_data_grants", grant(w, w.profile2))
        conn.execute(
            sa.text(
                "UPDATE tutor_data_grants SET revoked_at = now(), revoke_reason = 'student' "
                "WHERE id = :id"
            ),
            {"id": first["id"]},
        )
        _insert_ok(conn, "tutor_data_grants", grant(w, w.profile))


def test_ck_late_tutor_cancel_requires_reason(schema_engine: sa.Engine) -> None:
    """Decision row 18: inside 24 h a tutor's cancellation needs a non-blank reason.

    The red case of SPEC §e.4: a tutor-cancelled row inside 24 h with a NULL
    reason must be rejected, which only holds while the CHECK keeps its
    ``cancel_reason IS NOT NULL`` conjunct.
    """
    start = BASE

    def cancelled(
        at: datetime, *, by: str = "tutor", reason: str | None = None
    ) -> dict[str, object]:
        return _booking_row(
            w,
            start=start,
            state="cancelled",
            cancelled_at=at,
            cancelled_by_party=by,
            cancel_reason=reason,
        )

    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        inside = start - timedelta(hours=2)
        for reason in (None, "   "):
            _insert_violates(
                conn,
                "tutor_bookings",
                cancelled(inside, reason=reason),
                sqlstate="23514",
                constraint="ck_tutor_bookings_late_cancel_reason",
            )
        _insert_ok(conn, "tutor_bookings", cancelled(inside, reason="I am unwell"))
        _insert_ok(conn, "tutor_bookings", cancelled(start - timedelta(hours=24)))  # not late
        _insert_ok(conn, "tutor_bookings", cancelled(start - timedelta(hours=25)))
        _insert_ok(conn, "tutor_bookings", cancelled(inside, by="student"))  # not a tutor


# ---------------------------------------------------------------------------
# Composite foreign keys and RESTRICT (F34, F18, SC-21)
# ---------------------------------------------------------------------------


def test_review_composite_fk_rejects_mismatched_tutor(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        booking = _booking(conn, w)

        def review(**override: object) -> dict[str, object]:
            return {
                "id": uuid.uuid4(),
                "booking_id": booking,
                "tutor_profile_id": w.profile,
                "student_id": w.student,
                "stars": 4,
                "text_state": "none",
            } | override

        _insert_violates(
            conn,
            "tutor_reviews",
            review(tutor_profile_id=w.profile2),
            sqlstate="23503",
            constraint="fk_tutor_reviews_booking_tutor_tutor_bookings",
        )
        _insert_violates(
            conn,
            "tutor_reviews",
            review(student_id=w.student2),
            sqlstate="23503",
            constraint="fk_tutor_reviews_booking_student_tutor_bookings",
        )
        matching = review()
        _insert_ok(conn, "tutor_reviews", matching)
        reply = {"id": uuid.uuid4(), "review_id": matching["id"], "body": "Thank you"}
        _insert_violates(
            conn,
            "tutor_review_replies",
            reply | {"tutor_profile_id": w.profile2},
            sqlstate="23503",
            constraint="fk_tutor_review_replies_review_tutor_tutor_reviews",
        )
        _insert_ok(conn, "tutor_review_replies", reply | {"tutor_profile_id": w.profile})


def test_delete_user_with_booking_restricted(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _booking(conn, w)
        _violation(
            conn,
            lambda: conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": w.student}),
            sqlstate="23503",
            constraint="fk_tutor_bookings_student_id_users",
        )


def test_delete_tutor_user_restricted(schema_engine: sa.Engine) -> None:
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        _violation(
            conn,
            lambda: conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": w.tutor_user}),
            sqlstate="23503",
            constraint="fk_tutor_profiles_user_id_users",
        )


@pytest.mark.parametrize("dependent", ["booking", "grant", "report"])
def test_tutor_profile_delete_restricted_when_bookings_exist(
    schema_engine: sa.Engine, dependent: str
) -> None:
    """Profiles are closed, never deleted: no safeguarding record cascades away (SC-21)."""
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        if dependent == "booking":
            _booking(conn, w)
            constraint = "fk_tutor_bookings_tutor_profile_id_tutor_profiles"
        elif dependent == "grant":
            _insert(
                conn,
                "tutor_data_grants",
                {"id": uuid.uuid4(), "student_id": w.student, "tutor_profile_id": w.profile},
            )
            constraint = "fk_tutor_data_grants_tutor_profile_id_tutor_profiles"
        else:
            _insert(conn, "tutoring_reports", _report_row(w))
            constraint = "fk_tutoring_reports_tutor_profile_id_tutor_profiles"
        _violation(
            conn,
            lambda: conn.execute(
                sa.text("DELETE FROM tutor_profiles WHERE id = :id"), {"id": w.profile}
            ),
            sqlstate="23503",
            constraint=constraint,
        )


# ---------------------------------------------------------------------------
# Every CHECK constraint (SPEC §a.2)
# ---------------------------------------------------------------------------


def _report_row(w: World) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "reporter_user_id": w.student,
        "reporter_party": "student",
        "target_type": "tutor_profile",
        "tutor_profile_id": w.profile,
        "target_snapshot": "{}",
        "reason": "spam",
    }


def _base_row(conn: sa.Connection, w: World, table: str) -> dict[str, object]:
    """A valid row for ``table``, creating whatever rows it references first."""
    if table == "tutor_profiles":
        return _profile_row(_user(conn, "teacher"))
    if table == "tutor_availability_rules":
        return {
            "id": uuid.uuid4(),
            "tutor_profile_id": w.profile,
            "iso_weekday": 1,
            "start_minute": 600,
            "end_minute": 660,
        }
    if table == "tutor_evidence_files":
        return {
            "id": uuid.uuid4(),
            "tutor_profile_id": w.profile,
            "storage_path": f"tutor-evidence/{w.profile}/{uuid.uuid4()}.pdf",
            "original_filename": "certificate.pdf",
            "content_type": "application/pdf",
            "size_bytes": 100,
        }
    if table == "tutor_approval_events":
        return {
            "id": uuid.uuid4(),
            "tutor_profile_id": w.profile,
            "admin_user_id": w.admin,
            "decision": "approved",
            "profile_snapshot": "{}",
        }
    if table == "tutor_bookings":
        return _booking_row(w, start=BASE + timedelta(days=2))
    if table == "tutor_booking_notes":
        return {
            "id": uuid.uuid4(),
            "booking_id": _booking(conn, w),
            "author_user_id": w.student,
            "author_party": "student",
            "body": "See you then.",
        }
    if table == "tutor_reviews":
        return {
            "id": uuid.uuid4(),
            "booking_id": _booking(conn, w),
            "tutor_profile_id": w.profile,
            "student_id": w.student,
            "stars": 5,
            "text_state": "none",
        }
    if table == "tutor_review_replies":
        return {
            "id": uuid.uuid4(),
            "review_id": _review(conn, w, _booking(conn, w)),
            "tutor_profile_id": w.profile,
            "body": "Thank you.",
        }
    if table == "tutor_data_grants":
        return {
            "id": uuid.uuid4(),
            "student_id": w.student,
            "tutor_profile_id": w.profile,
            "created_at": BASE,
        }
    if table == "tutoring_reports":
        return _report_row(w)
    if table == "tutoring_blocks":
        return {"blocker_user_id": w.student, "blocked_user_id": w.tutor_user}
    raise AssertionError(f"no base row for {table}")


#: (constraint, table, columns that violate exactly that constraint)
CHECK_CASES: list[tuple[str, str, dict[str, object]]] = [
    ("ck_tutor_profiles_first_name_len", "tutor_profiles", {"public_first_name": "   "}),
    ("ck_tutor_profiles_first_name_chars", "tutor_profiles", {"public_first_name": "Sara2"}),
    ("ck_tutor_profiles_first_name_chars", "tutor_profiles", {"public_first_name": "s@ra"}),
    ("ck_tutor_profiles_headline_not_blank", "tutor_profiles", {"headline": "  "}),
    ("ck_tutor_profiles_bio_len", "tutor_profiles", {"bio": "x" * 2001}),
    (
        "ck_tutor_profiles_qualification_note_len",
        "tutor_profiles",
        {"qualification_note": "x" * 1001},
    ),
    ("ck_tutor_profiles_has_mode", "tutor_profiles", {"offers_virtual": False}),
    ("ck_tutor_profiles_other_note", "tutor_profiles", {"other_mode_note": "By phone"}),
    ("ck_tutor_profiles_closed", "tutor_profiles", {"listing_state": "closed"}),
    ("ck_tutor_profiles_closed", "tutor_profiles", {"closed_at": BASE}),
    ("ck_tutor_profiles_rating_count_nonneg", "tutor_profiles", {"rating_count": -1}),
    (
        "ck_tutor_profiles_rating_sum_range",
        "tutor_profiles",
        {"rating_count": 1, "rating_sum": 6},
    ),
    (
        "ck_tutor_availability_rules_iso_weekday_range",
        "tutor_availability_rules",
        {"iso_weekday": 8},
    ),
    (
        "ck_tutor_availability_rules_start_minute_range",
        "tutor_availability_rules",
        {"start_minute": 601},
    ),
    (
        "ck_tutor_availability_rules_end_minute_range",
        "tutor_availability_rules",
        {"end_minute": 600},
    ),
    (
        "ck_tutor_evidence_files_content_type_allowed",
        "tutor_evidence_files",
        {"content_type": "image/gif"},
    ),
    ("ck_tutor_evidence_files_size_bytes_range", "tutor_evidence_files", {"size_bytes": 0}),
    ("ck_tutor_approval_events_note_len", "tutor_approval_events", {"note": "x" * 2001}),
    (
        "ck_tutor_bookings_requested_by_party_allowed",
        "tutor_bookings",
        {"requested_by_party": "tutor"},
    ),
    (
        "ck_tutor_bookings_duration",
        "tutor_bookings",
        {"ends_at": BASE + timedelta(days=2, minutes=20)},
    ),
    (
        "ck_tutor_bookings_duration",
        "tutor_bookings",
        {"ends_at": BASE + timedelta(days=2, hours=4, minutes=15)},
    ),
    (
        "ck_tutor_bookings_meeting_link_mode",
        "tutor_bookings",
        {"mode": "in_person", "meeting_link": LINK},
    ),
    ("ck_tutor_bookings_location_detail_mode", "tutor_bookings", {"location_detail": "Library"}),
    ("ck_tutor_bookings_other_mode_note_mode", "tutor_bookings", {"other_mode_note": "Phone"}),
    (
        "ck_tutor_bookings_accepted_ts",
        "tutor_bookings",
        {"state": "accepted", "meeting_link": LINK},
    ),
    ("ck_tutor_bookings_declined_ts", "tutor_bookings", {"state": "declined"}),
    (
        "ck_tutor_bookings_cancelled_ts",
        "tutor_bookings",
        {"state": "cancelled", "cancelled_at": BASE},
    ),
    (
        "ck_tutor_bookings_completed_ts",
        "tutor_bookings",
        {"state": "completed", "accepted_at": BASE, "meeting_link": LINK, "completed_at": BASE},
    ),
    (
        "ck_tutor_bookings_no_show_ts",
        "tutor_bookings",
        {"state": "no_show", "accepted_at": BASE, "meeting_link": LINK},
    ),
    ("ck_tutor_bookings_expired_ts", "tutor_bookings", {"state": "expired"}),
    (
        "ck_tutor_bookings_virtual_link",
        "tutor_bookings",
        {"state": "accepted", "accepted_at": BASE},
    ),
    (
        "ck_tutor_bookings_in_person_location",
        "tutor_bookings",
        {"state": "accepted", "accepted_at": BASE, "mode": "in_person"},
    ),
    (
        "ck_tutor_bookings_late_cancel_reason",
        "tutor_bookings",
        {
            "state": "cancelled",
            "cancelled_by_party": "tutor",
            "cancelled_at": BASE + timedelta(days=2) - timedelta(hours=1),
        },
    ),
    (
        "ck_tutor_booking_notes_author_party_allowed",
        "tutor_booking_notes",
        {"author_party": "parent"},
    ),
    ("ck_tutor_booking_notes_body_len", "tutor_booking_notes", {"body": "   "}),
    ("ck_tutor_booking_notes_body_len", "tutor_booking_notes", {"body": "x" * 2001}),
    ("ck_tutor_reviews_stars_range", "tutor_reviews", {"stars": 6}),
    ("ck_tutor_reviews_stars_range", "tutor_reviews", {"stars": 0}),
    ("ck_tutor_reviews_body_len", "tutor_reviews", {"body": "x" * 1001, "text_state": "pending"}),
    ("ck_tutor_reviews_text_state_matches_body", "tutor_reviews", {"text_state": "pending"}),
    (
        "ck_tutor_reviews_text_state_matches_body",
        "tutor_reviews",
        {"body": "Great", "text_state": "none"},
    ),
    ("ck_tutor_review_replies_body_len", "tutor_review_replies", {"body": "  "}),
    ("ck_tutor_review_replies_text_state_allowed", "tutor_review_replies", {"text_state": "none"}),
    ("ck_tutor_data_grants_expires_after_created", "tutor_data_grants", {"expires_at": BASE}),
    (
        "ck_tutor_data_grants_revoked_after_created",
        "tutor_data_grants",
        {"revoked_at": BASE - timedelta(seconds=1), "revoke_reason": "student"},
    ),
    (
        "ck_tutor_data_grants_revoke_reason_matches",
        "tutor_data_grants",
        {"revoked_at": BASE + timedelta(seconds=1)},
    ),
    (
        "ck_tutor_data_grants_revoke_reason_matches",
        "tutor_data_grants",
        {"revoke_reason": "student"},
    ),
    (
        "ck_tutoring_reports_reporter_party_allowed",
        "tutoring_reports",
        {"reporter_party": "system"},
    ),
    ("ck_tutoring_reports_one_target", "tutoring_reports", {"target_type": "review"}),
    ("ck_tutoring_reports_one_target", "tutoring_reports", {"booking_id": uuid.uuid4()}),
    ("ck_tutoring_reports_details_len", "tutoring_reports", {"details": "x" * 1001}),
    (
        "ck_tutoring_reports_resolution_matches_state",
        "tutoring_reports",
        {"resolution": "dismissed"},
    ),
    (
        "ck_tutoring_reports_resolution_matches_state",
        "tutoring_reports",
        {"state": "dismissed"},
    ),
    (
        "ck_tutoring_reports_resolution_note_len",
        "tutoring_reports",
        {"resolution_note": "x" * 1001},
    ),
    ("ck_tutoring_blocks_not_self", "tutoring_blocks", {"blocked_user_id": "<student>"}),
]


@pytest.mark.parametrize(
    "case", CHECK_CASES, ids=[f"{index:02d}-{case[0]}" for index, case in enumerate(CHECK_CASES)]
)
def test_every_check_constraint_rejects_its_violation(
    schema_engine: sa.Engine, case: tuple[str, str, dict[str, object]]
) -> None:
    constraint, table, overrides = case
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        base = _base_row(conn, w, table)
        resolved = {k: (w.student if v == "<student>" else v) for k, v in overrides.items()}
        _insert_violates(conn, table, base | resolved, sqlstate="23514", constraint=constraint)
        # Control: the same row without the override is valid, so the override
        # alone is what the constraint refused.
        _insert_ok(conn, table, base)


def test_check_cases_cover_every_check_constraint(schema_engine: sa.Engine) -> None:
    """Non-vacuity for the test above: one case per catalogue CHECK, SPEC's named ones included."""
    with schema_engine.connect() as conn:
        catalogue = set(
            conn.execute(
                sa.text(
                    "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "WHERE c.contype = 'c' AND t.relname = ANY(:tables)"
                ),
                {"tables": list(TUTORING_TABLES)},
            ).scalars()
        )
    covered = {case[0] for case in CHECK_CASES}
    spec_named_checks = {name for name in spec_names_for(TUTORING_TABLES) if name.startswith("ck_")}
    assert covered == catalogue
    assert spec_named_checks <= covered
    assert len(spec_named_checks) == 15
    assert len(covered) == 46


def test_indexable_defaults_true(schema_engine: sa.Engine) -> None:
    """Row 17: a public card is indexable unless the tutor opts out."""
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        indexable = conn.execute(
            sa.text("SELECT indexable FROM tutor_profiles WHERE id = :id"), {"id": w.profile}
        ).scalar_one()
    assert indexable is True


# ---------------------------------------------------------------------------
# Effective-state predicates (SPEC §a.3)
# ---------------------------------------------------------------------------


def _coherent(state: str, now: datetime) -> dict[str, object]:
    """The timestamp/party columns the coherence CHECKs require for ``state``."""
    accepted = {"accepted_at": now, "meeting_link": LINK}
    return {
        "requested": {},
        "accepted": accepted,
        "declined": {"declined_at": now},
        "cancelled": {"cancelled_at": now, "cancelled_by_party": "student"},
        "completed": accepted | {"completed_at": now, "completed_by_party": "tutor"},
        "no_show": accepted | {"no_show_marked_at": now},
        "expired": {"expired_at": now},
    }[state]


#: SPEC §a.3: (stored state, time position) -> effective state.
_EXPECTED_EFFECTIVE = {
    ("requested", "future"): "requested",
    ("requested", "in_progress"): "expired",
    ("requested", "ended"): "expired",
    ("accepted", "future"): "accepted",
    ("accepted", "in_progress"): "accepted",
    ("accepted", "ended"): "awaiting_outcome",
}


def test_effective_state_predicates_cover_every_effective_state(schema_engine: sa.Engine) -> None:
    """Every stored state at every time position matches exactly one effective-state fragment."""
    expected_keys = {state.value for state in BookingState} | {"awaiting_outcome"}
    assert set(EFFECTIVE_STATE_SQL) == expected_keys
    now = datetime.now(UTC)
    positions = {
        "future": now + timedelta(days=2),
        "in_progress": now - timedelta(minutes=30),
        "ended": now - timedelta(hours=3),
    }
    selects = ", ".join(f"{sql} AS {name}" for name, sql in EFFECTIVE_STATE_SQL.items())
    seen: set[str] = set()
    checked = 0
    with _rolled_back(schema_engine) as conn:
        w = _world(conn)
        for state in BookingState:
            for position, start in positions.items():
                row = _booking_row(w, start=start, state=state.value, **_coherent(state.value, now))
                with conn.begin_nested() as savepoint:
                    _insert(conn, "tutor_bookings", row)
                    result = conn.execute(
                        sa.text(f"SELECT {selects} FROM tutor_bookings WHERE id = :id"),  # noqa: S608 - module constants
                        {"id": row["id"]},
                    ).one()
                    savepoint.rollback()
                matches = [name for name, value in result._mapping.items() if value]
                assert len(matches) == 1, (state.value, position, matches)
                want = _EXPECTED_EFFECTIVE.get((state.value, position), state.value)
                assert matches == [want], (state.value, position)
                seen.add(matches[0])
                checked += 1
    assert checked == len(BookingState) * len(positions)
    assert seen == expected_keys
