"""Migration 0044_tutoring_enums_ext: btree_gist, 16 enum types, 8 notification toggles.

Also the home of the helpers every tutoring schema test shares (precedent:
``tests/test_claude_images.py`` imports from ``tests/test_anthropic_adapter``):

* **SPEC parsers.** The expected side of every name check is parsed from
  ``docs/tutoring/SPEC.md`` §a.1/§a.2, never typed out again here (PLAN §0.8:
  no self-comparison with a literal written from the same source).
* **Catalogue readers** over ``pg_constraint``/``pg_indexes``/``pg_enum``.
* :func:`upgrade_head`, the missing half of ``migrated_sessionmaker_with_downgrade``.
  That fixture keeps ``LEMELY_DATABASE__URL`` pointed at its throwaway database
  for the whole test, and ``env.py`` re-derives the URL from settings, so a
  plain ``command.upgrade`` here migrates that same database.
"""

from __future__ import annotations

import functools
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from sqlalchemy.orm import Session, sessionmaker

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "tutoring" / "SPEC.md"

REVISION = "0044_tutoring_enums_ext"
DOWN_REVISION = "0043_merge_heads"


# ---------------------------------------------------------------------------
# SPEC parsers
# ---------------------------------------------------------------------------


@functools.cache
def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def spec_between(start: str, end: str) -> str:
    text = spec_text()
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def spec_enum_types() -> dict[str, tuple[str, ...]]:
    """SPEC §a.1's table: Postgres type name -> its values, in order."""
    section = spec_between("### a.1 Enum types", "**Additive values on an existing type**")
    types: dict[str, tuple[str, ...]] = {}
    for match in re.finditer(r"^\| `([a-z]+)` \| (.+?) \| `[A-Za-z]+` \|$", section, re.MULTILINE):
        types[match.group(1)] = tuple(re.findall(r"`([a-z_]+)`", match.group(2)))
    return types


def spec_new_notification_types() -> tuple[str, ...]:
    """The 8 ``notificationtype`` values SPEC §a.1 adds."""
    section = spec_between(
        "**Additive values on an existing type**", "**Additive columns on an existing table**"
    )
    body = section.split("\n", 1)[1]
    return tuple(re.findall(r"`([a-z_]+)`", body))


def spec_preference_role_table() -> dict[str, frozenset[str]]:
    """SPEC §a.1's role-gating table: notification type -> roles that may see and set it."""
    section = spec_between("Role gating of the 8 toggles", "`school_admin` gets none of the 8.")
    table: dict[str, frozenset[str]] = {}
    for match in re.finditer(r"^\| `([a-z_]+)` \| ([a-z_, ]+) \|", section, re.MULTILINE):
        table[match.group(1)] = frozenset(r.strip() for r in match.group(2).split(","))
    return table


@functools.cache
def spec_a2_sections() -> dict[str, str]:
    """SPEC §a.2, split per table: ``{table name: that table's section text}``."""
    body = spec_between("### a.2 Tables", "### a.3 State machines")
    parts = re.split(r"^#### `([a-z_]+)`.*$", body, flags=re.MULTILINE)
    # parts = [preamble, name1, text1, name2, text2, ...]
    return dict(zip(parts[1::2], parts[2::2], strict=True))


_NAMED = re.compile(r"(pk|uq|ix|ck|fk|excl)_[a-z0-9_]*[a-z0-9]")


def spec_named_objects(table: str) -> set[str]:
    """Every constraint/index name SPEC §a.2 gives for ``table``.

    Reads the backticked names (``ix_tutor_bookings_tutor_starts``), the
    ``ck_..._has_mode`` shorthand (the convention's own ``ck_<table>_`` prefix),
    the ``_mode_in_person`` suffix shorthand (same kind and table as the full
    name before it), and the bullet list under "Coherence CHECKs".
    """
    section = spec_a2_sections()[table]
    names: set[str] = set()
    previous_kind: str | None = None
    for token in re.findall(r"`([^`]+)`", section):
        if token.startswith("ck_..._"):
            names.add(f"ck_{table}_{token.removeprefix('ck_..._')}")
            continue
        match = _NAMED.match(token)
        if match and (match.end() == len(token) or token[match.end()] in " ("):
            names.add(match.group(0))
            previous_kind = match.group(1)
            continue
        if previous_kind and re.fullmatch(r"_[a-z0-9_]+", token):
            names.add(f"{previous_kind}_{table}{token}")
    if "Coherence CHECKs" in section:
        block = section.split("Coherence CHECKs", 1)[1].split("Exclusion and uniqueness", 1)[0]
        for match in re.finditer(r"^- `([a-z_]+)`(?: \([^)]*\))?:", block, re.MULTILINE):
            names.add(f"ck_{table}_{match.group(1)}")
    return names


def spec_tutoring_tables() -> tuple[str, ...]:
    return tuple(spec_a2_sections())


# ---------------------------------------------------------------------------
# Catalogue readers (``conn`` is a Connection or a Session)
# ---------------------------------------------------------------------------


def public_tables(conn: sa.Connection | Session) -> set[str]:
    return set(
        conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )


def object_names(conn: sa.Connection | Session, tables: Iterable[str]) -> set[str]:
    """Names of every constraint and index on ``tables``."""
    tables = list(tables)
    constraints = conn.execute(
        sa.text(
            "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'public' AND t.relname = ANY(:tables)"
        ),
        {"tables": tables},
    ).scalars()
    indexes = conn.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = ANY(:tables)"
        ),
        {"tables": tables},
    ).scalars()
    return set(constraints) | set(indexes)


def enum_labels(conn: sa.Connection | Session, typname: str) -> list[str]:
    return list(
        conn.execute(
            sa.text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = :name ORDER BY e.enumsortorder"
            ),
            {"name": typname},
        ).scalars()
    )


def type_exists(conn: sa.Connection | Session, typname: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT count(*) FROM pg_type WHERE typname = :name"), {"name": typname}
        ).scalar_one()
    )


def extension_installed(conn: sa.Connection | Session, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT count(*) FROM pg_extension WHERE extname = :name"), {"name": name}
        ).scalar_one()
    )


def column_names(conn: sa.Connection | Session, table: str) -> set[str]:
    return set(
        conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table"
            ),
            {"table": table},
        ).scalars()
    )


def current_revision(conn: sa.Connection | Session) -> str:
    return str(conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one())


def upgrade_head() -> None:
    """``alembic upgrade head`` against the fixture's throwaway database (see module docstring)."""
    command.upgrade(Config("alembic.ini"), "head")


def head_revision() -> str:
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert head is not None
    return head


def spec_names_for(tables: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for table in tables:
        names |= spec_named_objects(table)
    return names


def assert_named_objects_present(conn: sa.Connection | Session, tables: Iterable[str]) -> None:
    tables = tuple(tables)
    expected = spec_names_for(tables)
    missing = expected - object_names(conn, tables)
    assert not missing, sorted(missing)


def assert_round_trip(
    sm: sessionmaker[Session],
    downgrade_to: Callable[[str], None],
    *,
    tables: tuple[str, ...],
    down_revision: str,
    survivors: tuple[str, ...] = (),
) -> None:
    """Head -> ``down_revision`` -> head: ``tables`` go and come back with every SPEC name.

    ``survivors`` are tutoring tables of earlier revisions, which the downgrade
    must leave in place.
    """
    with sm() as session:
        assert set(tables) <= public_tables(session)
        assert_named_objects_present(session, tables)

    downgrade_to(down_revision)

    with sm() as session:
        assert current_revision(session) == down_revision
        assert not set(tables) & public_tables(session)
        assert set(survivors) <= public_tables(session)

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        assert set(tables) <= public_tables(session)
        assert_named_objects_present(session, tables)


# ---------------------------------------------------------------------------
# 0044's own checks
# ---------------------------------------------------------------------------


def _assert_0044_objects_present(sm: sessionmaker[Session]) -> None:
    enums = spec_enum_types()
    new_types = spec_new_notification_types()
    with sm() as session:
        assert extension_installed(session, "btree_gist")
        for typname, values in enums.items():
            assert enum_labels(session, typname) == list(values), typname
        assert set(new_types) <= set(enum_labels(session, "notificationtype"))
        assert set(new_types) <= column_names(session, "notification_preferences")


def test_spec_parsers_find_every_enum_and_notification_type() -> None:
    """Non-vacuity: the parsed SPEC tables have the sizes SPEC §a.1 and §f state in prose."""
    assert len(spec_enum_types()) == 16
    assert all(spec_enum_types().values())
    assert len(spec_new_notification_types()) == 8
    assert set(spec_preference_role_table()) == set(spec_new_notification_types())


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """At head: btree_gist, the 16 types with SPEC's values in order, 8 values, 8 columns."""
    _assert_0044_objects_present(migrated_sessionmaker)
    with migrated_sessionmaker() as session:
        rows = session.execute(
            sa.text(
                "SELECT column_name, is_nullable, column_default, data_type "
                "FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' AND column_name = ANY(:names)"
            ),
            {"names": list(spec_new_notification_types())},
        ).all()
    assert len(rows) == 8
    for row in rows:
        assert row.is_nullable == "NO", row.column_name
        assert row.column_default == "true", row.column_name
        assert row.data_type == "boolean", row.column_name


def test_notification_type_labels_match_preference_columns_after_migration(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """SPEC §e.4: the enum/preference-column pin holds on the migrated schema too."""
    with migrated_sessionmaker() as session:
        labels = set(enum_labels(session, "notificationtype"))
        toggles = column_names(session, "notification_preferences") - {
            "user_id",
            "quiet_hours_start",
            "quiet_hours_end",
            "created_at",
            "updated_at",
        }
    assert toggles == labels


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    new_types = spec_new_notification_types()
    user_id = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'teacher')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO notifications (user_id, type, title) "
                "VALUES (:u, 'booking_request', 'new'), (:u, 'grade_ready', 'old')"
            ),
            {"u": user_id},
        )
    _assert_0044_objects_present(sm)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        for typname in spec_enum_types():
            assert not type_exists(session, typname), typname
        assert not set(new_types) & column_names(session, "notification_preferences")
        # Pre-0044 code cannot load the new types, so their rows are gone; the
        # rest of the inbox is untouched.
        types = set(
            session.execute(
                sa.text("SELECT type::text FROM notifications WHERE user_id = :u"), {"u": user_id}
            ).scalars()
        )
        assert types == {"grade_ready"}
        # Postgres has no DROP VALUE: the 8 labels stay (precedent 0039).
        assert set(new_types) <= set(enum_labels(session, "notificationtype"))

    upgrade_head()

    _assert_0044_objects_present(sm)


def test_enums_downgrade_keeps_btree_gist(migrated_sessionmaker_with_downgrade) -> None:
    """F35: the extension may predate 0044, so its downgrade never drops it."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        assert extension_installed(session, "btree_gist")

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert extension_installed(session, "btree_gist")
