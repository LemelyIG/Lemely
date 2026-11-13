"""``POST /api/billing/checkout/pack`` and the payer's phone (UD-11): 422 ``phone_required``.

Paymob needs ``billing_data.phone_number``. Lemely never invents one: a payer with no valid
phone is refused before any payment row is written or Paymob is called, and the 422 carries the
stable code the client matches on.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import Payment
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import (
    get_billing_sessionmaker,
    get_checkout_limiter,
    get_paymob_client,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from tests.paymob_fixtures import (
    PAYMOB_SETTINGS,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def paymob() -> FakePaymobClient:
    return FakePaymobClient()


@pytest.fixture
def client(
    migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> Iterator[TestClient]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_billing_sessionmaker] = lambda: migrated_sessionmaker
    app.dependency_overrides[get_paymob_client] = lambda: paymob
    app.dependency_overrides[get_checkout_limiter] = lambda: SlidingWindowLimiter(
        limit=100, window_seconds=60, clock=time.monotonic
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(user_id), role=role.value
    )


@pytest.mark.parametrize(
    "stored", [None, "", "   ", "NA", "12345", "+200000000000", "call me", "+20\u0e51\u0e50"]
)
@pytest.mark.parametrize("role", [Role.student, Role.teacher])
def test_a_payer_without_a_valid_phone_is_422_phone_required(
    client: TestClient,
    migrated_sessionmaker: sessionmaker[Session],
    paymob: FakePaymobClient,
    role: Role,
    stored: str | None,
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm, role, phone=stored)
    _as(client, payer, role)

    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "phone_required"
    assert detail["message"]
    assert paymob.intentions == []  # Paymob is never called, and no number is invented
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_parent_without_a_phone_is_refused_though_the_child_has_one(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent, phone=None)
    child = seed_user(sm, Role.student, phone="+201012345678")
    link_parent(sm, parent_id=parent, child_id=child)
    _as(client, parent, Role.parent)

    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(seed_pack(sm)), "beneficiaryId": str(child)},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "phone_required"
    assert paymob.intentions == []


def test_a_payer_with_a_phone_checks_out_and_paymob_gets_that_exact_number(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm, Role.student, phone="010 1234 5678")
    _as(client, payer, Role.student)

    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})

    assert response.status_code == 201, response.text
    (body,) = paymob.intentions
    assert body["billing_data"]["phone_number"] == "+201012345678"


def test_adding_a_phone_unblocks_checkout(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm, Role.student, phone=None)
    pack = seed_pack(sm)
    _as(client, payer, Role.student)
    assert (
        client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)}).status_code
        == 422
    )

    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE users SET phone = :p WHERE id = :i"), {"p": "+201012345678", "i": payer}
        )

    assert (
        client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)}).status_code
        == 201
    )
    assert paymob.intentions[0]["billing_data"]["phone_number"] == "+201012345678"
