"""POST /api/webhooks/paymob/transaction end to end (spec §5.1 step 4, §5.5, §6, §9 router)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from structlog.testing import capture_logs

from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import (
    Payment,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    SavedCard,
)
from lemely.db.models.usage import UsageGrant
from lemely.runtime.config import PaymobSettings, Settings
from lemely.web import create_app
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from tests.paymob_fixtures import (
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    sign_token,
    sign_transaction,
    token_callback,
    token_obj,
    transaction_callback,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator
    from typing import Any

    from fastapi import FastAPI
    from sqlalchemy.orm import Session

URL = "/api/webhooks/paymob/transaction"
_MAX_BODY_BYTES = 64 * 1024


@pytest.fixture
def app(migrated_sessionmaker: sessionmaker[Session]) -> Iterator[FastAPI]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_billing_sessionmaker] = lambda: migrated_sessionmaker
    application.dependency_overrides[get_paymob_client] = lambda: FakePaymobClient()
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _payment(sm: sessionmaker[Session]) -> uuid.UUID:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    return seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)


def _post(client: TestClient, body: dict[str, Any], hmac: str | None) -> Any:
    params = {"hmac": hmac} if hmac is not None else {}
    return client.post(URL, params=params, json=body)


def _status(sm: sessionmaker[Session], pid: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        return payment.status


def _count(sm: sessionmaker[Session], model: type[Any]) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(model)).all())


def test_a_signed_success_callback_pays_and_grants(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    response = _post(client, transaction_callback(obj), sign_transaction(obj))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _status(sm, pid) is PaymentStatus.paid
    with sm() as session:
        (grant,) = session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == pid)).all()
    assert grant.units == 100


def test_a_forged_signature_is_401_and_changes_nothing(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    forged = sign_transaction(obj, secret="attacker-guess")
    assert _post(client, transaction_callback(obj), forged).status_code == 401
    assert _post(client, transaction_callback(obj), None).status_code == 401
    assert _post(client, transaction_callback(obj), "").status_code == 401
    tampered = {**obj, "amount_cents": 1}
    assert _post(client, transaction_callback(tampered), sign_transaction(obj)).status_code == 401
    assert _status(sm, pid) is PaymentStatus.created
    assert _count(sm, PaymobEvent) == 0
    assert _count(sm, UsageGrant) == 0


def test_the_hmac_is_checked_before_the_database_is_touched(app: FastAPI) -> None:
    """A bad signature must be answered without so much as opening a session."""

    untouchable = MagicMock(spec=sessionmaker)
    untouchable.side_effect = AssertionError("a session was opened before the HMAC was verified")
    untouchable.begin.side_effect = untouchable.side_effect
    app.dependency_overrides[get_billing_sessionmaker] = lambda: untouchable
    obj = transaction_obj()
    http = TestClient(app, raise_server_exceptions=True)
    assert _post(http, transaction_callback(obj), "0" * 128).status_code == 401
    assert _post(http, transaction_callback(obj), None).status_code == 401
    obj = token_obj()
    assert _post(http, token_callback(obj), sign_transaction(obj)).status_code == 401


def test_a_duplicate_delivery_is_200_and_grants_once(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    for _ in range(3):
        response = _post(client, transaction_callback(obj), sign_transaction(obj))
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    assert _count(sm, UsageGrant) == 1
    assert _count(sm, PaymobEvent) == 1


def test_an_amount_mismatch_is_200_failed_mismatch_no_grant(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid), amount_cents=100)
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _status(sm, pid) is PaymentStatus.failed_mismatch
    assert _count(sm, UsageGrant) == 0


def test_an_unknown_reference_is_200_so_paymob_stops_retrying(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    obj = transaction_obj(merchant_order_id="no-such-payment")
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _count(sm, PaymobEvent) == 1


def test_a_signed_token_callback_saves_the_card(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _payment(sm)
    obj = token_obj(token="tok-live-1")
    response = _post(client, token_callback(obj), sign_token(obj))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # The repo method never commits: the card is visible to a fresh session only
    # because the route committed after it.
    with sm() as session:
        (card,) = session.scalars(sa.select(SavedCard)).all()
        (event,) = session.scalars(
            sa.select(PaymobEvent).where(PaymobEvent.kind == PaymobEventKind.token)
        ).all()
    assert "tok-live-1" not in card.token
    assert "tok-live-1" not in json.dumps(event.payload)


def test_a_replayed_token_callback_is_200_and_saves_one_card(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _payment(sm)
    obj = token_obj(token="tok-live-2")
    for _ in range(2):
        assert _post(client, token_callback(obj), sign_token(obj)).status_code == 200
    assert _count(sm, SavedCard) == 1
    assert _count(sm, PaymobEvent) == 1


def test_a_token_callback_signed_as_a_transaction_is_401(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _payment(sm)
    obj = token_obj()
    assert _post(client, token_callback(obj), sign_transaction(obj)).status_code == 401
    assert _count(sm, SavedCard) == 0
    assert _count(sm, PaymobEvent) == 0


def test_a_token_callback_without_its_token_is_400(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    obj = token_obj()
    del obj["token"]
    assert _post(client, token_callback(obj), sign_token(obj)).status_code == 400
    assert _count(migrated_sessionmaker, PaymobEvent) == 0


def test_other_callback_types_are_acknowledged_and_ignored(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    body = {"type": "DELIVERY_STATUS", "obj": {"order_id": 1}}
    response = _post(client, body, "anything")
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert _count(migrated_sessionmaker, PaymobEvent) == 0


@pytest.mark.parametrize("body", [{}, {"type": None}, {"type": ["TRANSACTION"]}, {"type": 7}])
def test_a_body_with_no_usable_type_is_ignored(client: TestClient, body: dict[str, Any]) -> None:
    response = _post(client, body, None)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.parametrize(
    "body",
    [
        {"type": "TRANSACTION"},
        {"type": "TRANSACTION", "obj": "x"},
        {"type": "TOKEN", "obj": [1, 2]},
        {"type": "TRANSACTION", "obj": None},
    ],
)
def test_a_body_without_an_obj_is_400(client: TestClient, body: dict[str, Any]) -> None:
    assert _post(client, body, "abc").status_code == 400


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"\xff\xfe\x00", b"[1, 2]", b'"TRANSACTION"', b"null", b"[" * 50_000],
)
def test_a_body_that_is_not_a_json_object_is_400(client: TestClient, raw: bytes) -> None:
    response = client.post(
        URL, params={"hmac": "abc"}, content=raw, headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


def test_a_signed_callback_missing_its_id_is_400(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    obj = transaction_obj()
    del obj["id"]
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 400
    assert _count(migrated_sessionmaker, PaymobEvent) == 0


def test_unconfigured_hmac_secret_is_503(client: TestClient) -> None:
    bare = Settings().model_copy(update={"paymob": PaymobSettings()})
    client.app.dependency_overrides[get_settings] = lambda: bare  # type: ignore[attr-defined]
    obj = transaction_obj()
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 503


def test_a_mismatch_is_logged_at_error_level_without_the_signature(client: TestClient) -> None:
    obj = transaction_obj()
    received = "ab" * 64
    with capture_logs() as logs:
        _post(client, transaction_callback(obj), received)
    mismatches = [e for e in logs if e["event"] == "paymob_hmac_mismatch"]
    assert mismatches
    assert all(e["log_level"] == "error" for e in mismatches)
    assert received not in json.dumps(logs, default=str)


# -- body size -----------------------------------------------------------------


def test_a_declared_oversized_body_is_413_before_it_is_parsed(client: TestClient) -> None:
    padding = "x" * (_MAX_BODY_BYTES + 1)
    response = client.post(
        URL, params={"hmac": "abc"}, json={"type": "TRANSACTION", "pad": padding}
    )
    assert response.status_code == 413


def test_an_oversized_chunked_body_is_413_too(client: TestClient) -> None:
    """No Content-Length to trust: the streamed bytes are counted."""

    def chunks() -> Iterator[bytes]:
        yield b'{"type": "TRANSACTION", "pad": "'
        for _ in range(_MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024
        yield b'"}'

    response = client.post(
        URL,
        params={"hmac": "abc"},
        content=chunks(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_a_real_callback_is_far_below_the_size_limit() -> None:
    obj = transaction_obj()
    assert len(json.dumps(transaction_callback(obj))) < _MAX_BODY_BYTES // 8


# -- failure after the HMAC passed ---------------------------------------------


def test_an_unexpected_error_rolls_back_and_is_not_a_200(
    app: FastAPI,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    signature = sign_transaction(obj)

    def explode(self: BillingService, payload: dict[str, Any]) -> None:
        # Write first (a flushed event row), then fail: the route must roll it back.
        self._record_event(PaymobEventKind.transaction, "txn:boom", {"id": 1})
        self._session.flush()
        raise RuntimeError(f"db exploded near {payload['id']} tok-secret-9 {signature}")

    monkeypatch.setattr(BillingService, "apply_transaction_callback", explode)
    http = TestClient(app, raise_server_exceptions=False)
    with capture_logs() as logs:
        response = _post(http, transaction_callback(obj), signature)
    assert response.status_code == 500
    assert response.status_code != 200
    assert _count(sm, PaymobEvent) == 0
    assert _status(sm, pid) is PaymentStatus.created
    rendered = json.dumps(logs, default=str) + response.text
    assert "tok-secret-9" not in rendered
    assert signature not in rendered
    assert any(e["event"] == "paymob_callback_failed" and e["log_level"] == "error" for e in logs)


def test_a_failed_attempt_leaves_the_retry_free_to_apply(
    app: FastAPI,
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paymob retries a 5xx: the first failure must not poison the dedupe key."""
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    signature = sign_transaction(obj)
    real = BillingService.apply_transaction_callback
    calls = {"n": 0}

    def flaky(self: BillingService, payload: dict[str, Any]) -> None:
        calls["n"] += 1
        real(self, payload)
        if calls["n"] == 1:
            raise RuntimeError("late failure after the apply")

    monkeypatch.setattr(BillingService, "apply_transaction_callback", flaky)
    http = TestClient(app, raise_server_exceptions=False)
    assert _post(http, transaction_callback(obj), signature).status_code == 500
    assert _status(sm, pid) is PaymentStatus.created
    assert _count(sm, PaymobEvent) == 0
    assert _post(http, transaction_callback(obj), signature).status_code == 200
    assert _status(sm, pid) is PaymentStatus.paid
    assert _count(sm, UsageGrant) == 1
