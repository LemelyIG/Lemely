"""A missing ``billing_settings`` row answers 503 with a code on the admin overview (UD-13).

The customer catalogues are covered in ``test_web_billing``. The row is restored after each test
(``emptied_after`` inserts it again), and nothing here reads a stand-in constant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.models.enums import Role
from tests.admin_billing_db import add_user, admin_client, billing_database, emptied_after

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def test_the_admin_overview_is_503_with_a_code_when_the_notice_setting_is_missing(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The grace read runs first and has its own 503 (UD13-C); isolate the notice read here.
    monkeypatch.setattr("lemely.db.admin_billing_repo.current_grace_days", lambda _session: 3)
    client = admin_client(sm, admin)
    assert client.get("/api/admin/billing/catalogue").status_code == 200
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM billing_settings"))
    with capture_logs() as logs:
        response = client.get("/api/admin/billing/catalogue")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "notice_setting_missing"
    assert detail["error"] == "notice_setting_missing"
    assert "temporarily unavailable" in detail["message"]
    assert [log["event"] for log in logs if log.get("alert")] == ["notice_setting_missing"]
