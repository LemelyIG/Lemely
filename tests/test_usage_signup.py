"""Spec §2.1 free start: the first verification issues the signup grant, once (Task 8)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, text, update

from lemely.auth import mirror as mirror_module
from lemely.auth.mirror import DbUserMirror
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.usage_catalogue_repo import grant_signup_allowance
from tests import test_email_verified_first_timestamp as _verified

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import Settings

# Re-exported by attribute (see tests/test_student_self_review_web.py for why).
db_settings = _verified.db_settings

FIRST = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _seed(factory: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _grants(factory: sessionmaker[Session], user: uuid.UUID) -> list[UsageGrant]:
    with factory() as session:
        return list(session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == user)))


def test_student_gets_one_hidden_allowance_on_first_verification(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    student = _seed(factory, Role.student)
    mirror = DbUserMirror(settings)
    mirror.mark_email_verified(student, verified_at=FIRST)
    mirror.mark_email_verified(student, verified_at=FIRST)
    (grant,) = _grants(factory, student)
    assert (grant.kind, grant.visible, grant.units, grant.expires_at) == (
        GrantKind.signup,
        False,
        250,
        None,
    )


def test_teacher_gets_thirty_day_visible_credits(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    teacher = _seed(factory, Role.teacher)
    DbUserMirror(settings).mark_email_verified(teacher, verified_at=FIRST)
    (grant,) = _grants(factory, teacher)
    assert grant.visible is True
    assert grant.units == 2000
    assert grant.expires_at == datetime(2026, 12, 4, 9, 0, tzinfo=UTC)


def test_parents_get_nothing_and_unknown_users_are_a_no_op(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    parent = _seed(factory, Role.parent)
    mirror = DbUserMirror(settings)
    mirror.mark_email_verified(parent, verified_at=FIRST)
    mirror.mark_email_verified(uuid.uuid4(), verified_at=FIRST)
    assert _grants(factory, parent) == []


def test_a_billing_failure_never_fails_the_verification(
    db_settings: tuple[Settings, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, factory = db_settings
    student = _seed(factory, Role.student)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(mirror_module, "grant_signup_allowance", _boom)
    DbUserMirror(settings).mark_email_verified(student, verified_at=FIRST)
    with factory() as session:
        stamped = session.scalar(select(User.email_verified_at).where(User.id == student))
    assert stamped == FIRST
    assert _grants(factory, student) == []


def test_a_blocked_second_verifier_gets_no_grant(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    """A holds the row lock mid-transaction; B blocks on it, then matches zero rows."""
    settings, factory = db_settings
    uid = _seed(factory, Role.student)
    mirror = DbUserMirror(settings)
    a = factory()
    role = a.execute(
        update(User)
        .where(User.id == uid, User.email_verified_at.is_(None))
        .values(email_verified_at=FIRST)
        .returning(User.role)
    ).scalar_one_or_none()
    assert role is Role.student
    done = threading.Event()
    errors: list[BaseException] = []

    def _second() -> None:
        try:
            mirror.mark_email_verified(uid, verified_at=FIRST)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_second)
    worker.start()
    time.sleep(0.5)
    assert not done.is_set(), "the second verifier should wait on the first one's row lock"
    with a.begin_nested():
        grant_signup_allowance(a, user_id=uid, role=role, now=FIRST)
    a.commit()
    a.close()
    worker.join(10)
    assert done.is_set()
    assert errors == []
    assert len(_grants(factory, uid)) == 1


def test_many_concurrent_verifiers_issue_one_grant(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    mirror = DbUserMirror(settings)
    for _ in range(5):
        uid = _seed(factory, Role.teacher)
        barrier = threading.Barrier(8)
        errors: list[BaseException] = []

        def _go(
            user: uuid.UUID = uid,
            gate: threading.Barrier = barrier,
            sink: list[BaseException] = errors,
        ) -> None:
            try:
                gate.wait()
                mirror.mark_email_verified(user, verified_at=FIRST)
            except BaseException as exc:
                sink.append(exc)

        threads = [threading.Thread(target=_go) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        assert errors == []
        assert len(_grants(factory, uid)) == 1


def test_a_database_error_inside_the_savepoint_does_not_fail_the_verification(
    db_settings: tuple[Settings, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, factory = db_settings
    uid = _seed(factory, Role.student)
    other = _seed(factory, Role.student)

    def _duplicate_key(session: Session, **_k: object) -> None:
        session.execute(
            text("INSERT INTO users (id, email, role) VALUES (:i, 'x@e.com', 'student')"),
            {"i": other},
        )

    monkeypatch.setattr(mirror_module, "grant_signup_allowance", _duplicate_key)
    DbUserMirror(settings).mark_email_verified(uid, verified_at=FIRST)
    with factory() as session:
        assert session.scalar(select(User.email_verified_at).where(User.id == uid)) == FIRST


def test_a_swallowed_grant_failure_is_not_retried_by_a_later_verification(
    db_settings: tuple[Settings, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, factory = db_settings
    uid = _seed(factory, Role.student)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(mirror_module, "grant_signup_allowance", _boom)
        DbUserMirror(settings).mark_email_verified(uid, verified_at=FIRST)
    DbUserMirror(settings).mark_email_verified(uid, verified_at=FIRST)
    assert _grants(factory, uid) == []
