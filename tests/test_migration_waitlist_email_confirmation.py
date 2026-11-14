"""Migration 0054_waitlist_email_confirmation: the emailed-confirmation columns.

Additive: four nullable columns and a partial unique index on the token digest. Existing rows
stay valid (unconfirmed, no token); the downgrade removes exactly what the upgrade added.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0054_waitlist_email_confirmation"
DOWN_REVISION = "0053_waitlist_applicant_name"
TABLE = "waitlist_applicants"
COLUMNS = {
    "email_confirmed_at",
    "confirm_token_hash",
    "confirm_token_expires_at",
    "confirm_sent_at",
    "confirm_prev_hashes",
    "confirm_send_count",
}
#: The two that are NOT NULL with a server default; the rest are nullable.
NOT_NULL = {"confirm_prev_hashes", "confirm_send_count"}
INDEX = "uq_waitlist_applicants_confirm_token_hash"

_COLUMNS_SQL = sa.text(
    "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = :t"
)


def _insert(session: Session, email: str, confirm_hash: str | None = None) -> None:
    session.execute(
        sa.text(
            "INSERT INTO waitlist_applicants "
            "(email, role, consent_version, consent_text, consent_at, confirm_token_hash) "
            "VALUES (:e, 'student', 'v', 'c', now(), :h)"
        ),
        {"e": email, "h": confirm_hash},
    )


def _columns(session: Session) -> dict[str, str]:
    return dict(session.execute(_COLUMNS_SQL, {"t": TABLE}).tuples().all())


def test_revision_chains_from_0053_and_is_the_head() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert head_revision() == REVISION


def test_columns_are_nullable_and_the_schema_matches_the_orm(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        columns = _columns(session)
        assert {c: columns[c] for c in COLUMNS} == {
            c: "NO" if c in NOT_NULL else "YES" for c in COLUMNS
        }
        _insert(session, "old@example.com")  # a pre-existing style row is still valid
        assert session.execute(
            sa.text("SELECT confirm_send_count, confirm_prev_hashes FROM waitlist_applicants")
        ).one() == (0, [])
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_a_confirmation_digest_is_unique_when_present(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        _insert(session, "a@example.com", "h1")
        _insert(session, "b@example.com", None)
        _insert(session, "c@example.com", None)  # many NULLs are fine
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        _insert(session, "d@example.com", "h1")


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        _insert(session, "keep@example.com")

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert not COLUMNS & set(_columns(session))
        indexes = set(
            session.execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": TABLE}
            ).scalars()
        )
        assert INDEX not in indexes
        assert session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1  # noqa: S608 - constant

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == REVISION
        assert set(_columns(session)) >= COLUMNS
