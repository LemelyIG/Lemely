"""The soft-delete loader criterion (design 2026-09-22 §3).

Every test here asserts the row is visible BEFORE it is stamped, so none of
them can pass against a database where the insert silently failed — and every
absence is followed by the ``include_deleted`` escape hatch returning the same
row, so none of them can pass because the row was actually removed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, aliased

from lemely.db.models import User
from lemely.db.models.attempts import Attempt, Upload
from lemely.db.models.enums import Role
from lemely.db.models.teacher_papers import TeacherPaper
from lemely.db.session import INCLUDE_DELETED, _exclude_soft_deleted

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


@dataclass(frozen=True)
class Seeded:
    user_id: uuid.UUID
    upload_id: uuid.UUID
    attempt_id: uuid.UUID


def _seed(sm: sessionmaker[Session]) -> Seeded:
    """A student, one upload, and one attempt against that upload — all live."""
    uid = uuid.uuid4()
    upload_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
        session.flush()
        session.add(Upload(id=upload_id, user_id=uid, storage_path=f"uploads/{upload_id}.pdf"))
        session.flush()
        session.add(
            Attempt(
                id=attempt_id,
                user_id=uid,
                upload_id=upload_id,
                subject_code="0625",
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                recorded_at=datetime.now(UTC),
            )
        )
    return Seeded(user_id=uid, upload_id=upload_id, attempt_id=attempt_id)


def _stamp(
    sm: sessionmaker[Session], model: type[Attempt | Upload | TeacherPaper], row_id: uuid.UUID
) -> None:
    """Soft-delete one row with a Core UPDATE (not filtered: it is not a select)."""
    with sm.begin() as session:
        result = session.execute(
            sa.update(model).where(model.id == row_id).values(deleted_at=datetime.now(UTC))
        )
        assert result.rowcount == 1  # type: ignore[attr-defined]


@pytest.fixture
def seeded_attempt(migrated_sessionmaker: sessionmaker[Session]) -> Seeded:
    return _seed(migrated_sessionmaker)


@pytest.fixture
def deleted_attempt(migrated_sessionmaker: sessionmaker[Session]) -> Seeded:
    seeded = _seed(migrated_sessionmaker)
    with migrated_sessionmaker() as session:
        # Present before the stamp, so the absences below are not vacuous.
        assert session.get(Attempt, seeded.attempt_id) is not None
    _stamp(migrated_sessionmaker, Attempt, seeded.attempt_id)
    return seeded


# ── Registration and import shape ─────────────────────────────────────────────


def test_listener_is_registered_at_class_level() -> None:
    """Instance-level registration would leave tests/conftest's own sessionmaker bare."""
    assert event.contains(Session, "do_orm_execute", _exclude_soft_deleted)


def test_include_deleted_constant_is_the_option_name() -> None:
    assert INCLUDE_DELETED == "include_deleted"


def test_db_package_imports_cleanly_in_a_fresh_interpreter() -> None:
    """``session.py`` must not import models at module top (review amendment B1).

    ``lemely.auth.mirror`` imports ``session_scope`` from a half-initialised
    ``session.py`` when the models load, so a top-level model import there
    breaks ``import lemely.db`` — and Alembic with it. Only a fresh interpreter
    sees that ordering; this process already has everything imported.
    """
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(repo_root))
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import lemely.db; import lemely.db.session; import lemely.db.review_repo",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr


# ── Attempt ───────────────────────────────────────────────────────────────────


def test_entity_select_hides_a_stamped_row(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    stmt = select(Attempt).where(Attempt.id == seeded_attempt.attempt_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is not None  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is None  # then absent


def test_include_deleted_is_the_escape_hatch(
    migrated_sessionmaker: sessionmaker[Session], deleted_attempt: Seeded
) -> None:
    stmt = select(Attempt).where(Attempt.id == deleted_attempt.attempt_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is None
        opted_in = session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).one_or_none()
        assert opted_in is not None
        assert opted_in.id == deleted_attempt.attempt_id
        assert opted_in.deleted_at is not None


def test_include_deleted_false_does_not_opt_out(
    migrated_sessionmaker: sessionmaker[Session], deleted_attempt: Seeded
) -> None:
    stmt = select(Attempt).where(Attempt.id == deleted_attempt.attempt_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).one_or_none()
        assert (
            session.scalars(stmt.execution_options(**{INCLUDE_DELETED: False})).one_or_none()
            is None
        )


def test_column_only_select_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    """seat_repo.py:369's exact shape — a column-only GROUP BY with no entity."""
    stmt = (
        select(Attempt.user_id, func.max(Attempt.recorded_at))
        .where(Attempt.user_id == seeded_attempt.user_id)
        .group_by(Attempt.user_id)
    )
    with migrated_sessionmaker() as session:
        assert session.execute(stmt).all() != []  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.execute(stmt).all() == []
        assert session.execute(stmt.execution_options(**{INCLUDE_DELETED: True})).all() != []


def test_explicit_join_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    stmt = (
        select(User.id)
        .join(Attempt, Attempt.user_id == User.id)
        .where(Attempt.id == seeded_attempt.attempt_id)
    )
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == [seeded_attempt.user_id]

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == []
        assert session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).all() == [
            seeded_attempt.user_id
        ]


def test_exists_subquery_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    stmt = select(User.id).where(
        User.id == seeded_attempt.user_id,
        select(Attempt.id).where(Attempt.user_id == User.id).exists(),
    )
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == [seeded_attempt.user_id]

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == []
        assert session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).all() == [
            seeded_attempt.user_id
        ]


def test_in_subquery_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    stmt = select(User.id).where(
        User.id == seeded_attempt.user_id,
        User.id.in_(select(Attempt.user_id)),
    )
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == [seeded_attempt.user_id]

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == []
        assert session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).all() == [
            seeded_attempt.user_id
        ]


def test_aliased_entity_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    alias = aliased(Attempt)
    stmt = select(alias.id).where(alias.id == seeded_attempt.attempt_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == [seeded_attempt.attempt_id]

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).all() == []
        assert session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).all() == [
            seeded_attempt.attempt_id
        ]


def test_lazy_load_of_a_relationship_is_filtered(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    """``upload.attempts`` is a lazy load that inherits the parent query's criterion."""
    with migrated_sessionmaker() as session:
        upload = session.get(Upload, seeded_attempt.upload_id)
        assert upload is not None
        assert [a.id for a in upload.attempts] == [seeded_attempt.attempt_id]  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        upload = session.get(Upload, seeded_attempt.upload_id)
        assert upload is not None
        assert upload.attempts == []

    with migrated_sessionmaker() as session:
        upload = session.get(
            Upload, seeded_attempt.upload_id, execution_options={INCLUDE_DELETED: True}
        )
        assert upload is not None
        assert [a.id for a in upload.attempts] == [seeded_attempt.attempt_id]


def test_session_get_on_a_cold_session_returns_none(
    migrated_sessionmaker: sessionmaker[Session], deleted_attempt: Seeded
) -> None:
    """placement_repo.py:332 and practice_repo.py:565 rely on this 404 path."""
    with migrated_sessionmaker() as session:
        assert session.get(Attempt, deleted_attempt.attempt_id) is None
        opted_in = session.get(
            Attempt, deleted_attempt.attempt_id, execution_options={INCLUDE_DELETED: True}
        )
        assert opted_in is not None
        assert opted_in.id == deleted_attempt.attempt_id


def test_a_live_row_is_never_hidden(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    with migrated_sessionmaker() as session:
        assert session.get(Attempt, seeded_attempt.attempt_id) is not None
        assert session.get(Upload, seeded_attempt.upload_id) is not None


def test_warm_identity_map_hides_a_concurrent_soft_delete(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    """Documented hazard: ``session.get`` on a warm identity map skips SQL entirely.

    ``_exclude_soft_deleted`` only runs on ``do_orm_execute`` -- it cannot
    intervene when no statement is executed. Once an ``Attempt`` is already in
    a session's identity map, ``session.get`` for the same id short-circuits to
    the cached object without issuing any SQL, so the filter never gets a
    chance to run -- even immediately after that same session soft-deletes the
    row via ``sa.update``. (The ``UPDATE`` itself does sync the cached
    object's ``deleted_at`` in place via SQLAlchemy's default
    ``synchronize_session`` evaluation, so the returned object is not stale --
    but code that treats ``session.get(...) is None`` as its "was this
    deleted" check will be fooled: the object is still returned, non-``None``.)
    Delete/restore code must re-fetch with a fresh ``select`` (which the
    do_orm_execute listener does see) rather than relying on ``session.get``
    to observe its own soft-delete within one session.
    """
    with migrated_sessionmaker() as session:
        attempt = session.get(Attempt, seeded_attempt.attempt_id)
        assert attempt is not None  # loaded into the identity map, live
        engine = session.get_bind()

        session.execute(
            sa.update(Attempt)
            .where(Attempt.id == seeded_attempt.attempt_id)
            .values(deleted_at=datetime.now(UTC))
        )

        queries: list[str] = []

        def _record(*args: object) -> None:
            queries.append(str(args[1]))

        event.listen(engine, "before_cursor_execute", _record)
        try:
            same_session_get = session.get(Attempt, seeded_attempt.attempt_id)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert same_session_get is attempt  # cached object, not re-fetched
        assert same_session_get is not None  # the hazard: not excluded, unlike a fresh select
        assert queries == []  # no SQL was issued to reach this answer at all

        session.commit()

    with migrated_sessionmaker() as fresh_session:
        assert fresh_session.get(Attempt, seeded_attempt.attempt_id) is None


# ── Upload ────────────────────────────────────────────────────────────────────


def test_upload_select_hides_a_stamped_row(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    stmt = select(Upload).where(Upload.id == seeded_attempt.upload_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is not None  # present first

    _stamp(migrated_sessionmaker, Upload, seeded_attempt.upload_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is None
        assert session.get(Upload, seeded_attempt.upload_id) is None
        opted_in = session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).one_or_none()
        assert opted_in is not None
        assert opted_in.id == seeded_attempt.upload_id


# ── TeacherPaper ──────────────────────────────────────────────────────────────


def test_teacher_paper_select_hides_a_stamped_row(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    teacher_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.add(User(id=teacher_id, email=f"{teacher_id}@example.com", role=Role.teacher))
        session.flush()
        session.add(
            TeacherPaper(
                id=paper_id, uploaded_by=teacher_id, storage_path=f"teacher/{paper_id}.pdf"
            )
        )

    stmt = select(TeacherPaper).where(TeacherPaper.id == paper_id)
    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is not None  # present first

    _stamp(migrated_sessionmaker, TeacherPaper, paper_id)

    with migrated_sessionmaker() as session:
        assert session.scalars(stmt).one_or_none() is None
        assert session.get(TeacherPaper, paper_id) is None
        opted_in = session.scalars(stmt.execution_options(**{INCLUDE_DELETED: True})).one_or_none()
        assert opted_in is not None
        assert opted_in.id == paper_id
