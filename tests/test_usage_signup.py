"""Spec §2.1 free start: the first verification issues the signup grant, once (Task 8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.auth import mirror as mirror_module
from lemely.auth.mirror import DbUserMirror
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant
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
