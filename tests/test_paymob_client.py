"""PaymobClient against handwritten fixtures through httpx.MockTransport (spec §3, §6)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from lemely.io.paymob.client import (
    AUTH_TOKEN_TTL_SECONDS,
    PaymobClient,
    PaymobError,
    PaymobNotConfigured,
)
from lemely.runtime.config import PaymobSettings
from tests.paymob_fixtures import (
    AUTH_TOKEN_RESPONSE,
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    PLAN_RESPONSE,
    SUBSCRIPTION_RESPONSE,
    transaction_obj,
)

if TYPE_CHECKING:
    from collections.abc import Callable

BASE = "https://accept.paymob.com"
INQUIRY_PATH = "/api/ecommerce/orders/transaction_inquiry"
SECRET_KEY = "egy_sk_test_secret"
API_KEY = "api_key_test"

Reply = tuple[int, Any]


class Recorder:
    """Route table for MockTransport: (method, path) -> reply, or a list of replies.

    A list is consumed in order and its last entry repeats, so a test can script
    "401 then 200" without a handler of its own.
    """

    def __init__(self, routes: dict[tuple[str, str], Reply | list[Reply]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(599, json={"detail": f"unrouted {key}"})
        reply = self.routes[key]
        if isinstance(reply, list):
            status, body = reply.pop(0) if len(reply) > 1 else reply[0]
        else:
            status, body = reply
        return httpx.Response(status, json=body)

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]

    def hits(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


AUTH = ("POST", "/api/auth/tokens")


def _client(
    routes: dict[tuple[str, str], Reply | list[Reply]],
    *,
    settings: PaymobSettings = PAYMOB_SETTINGS,
    clock: Callable[[], float] | None = None,
) -> tuple[PaymobClient, Recorder]:
    recorder = Recorder({AUTH: (200, AUTH_TOKEN_RESPONSE), **routes})
    client = PaymobClient(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(recorder)),
        clock=clock or Clock(),
    )
    return client, recorder


def _client_with_handler(handler: Callable[[httpx.Request], httpx.Response]) -> PaymobClient:
    return PaymobClient(PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler)))


# -- request shapes ------------------------------------------------------------


def test_create_intention_posts_with_the_secret_key_token_header() -> None:
    client, rec = _client({("POST", "/v1/intention/"): (201, INTENTION_RESPONSE)})
    body = {"amount": 10000, "currency": "EGP", "payment_methods": [4569876]}
    response = client.create_intention(body)
    assert response["client_secret"] == INTENTION_RESPONSE["client_secret"]
    (request,) = rec.requests
    assert str(request.url) == f"{BASE}/v1/intention/"
    assert request.headers["authorization"] == f"Token {SECRET_KEY}"
    assert json.loads(request.content) == body


def test_unconfigured_secret_key_fails_before_any_request() -> None:
    client, rec = _client({}, settings=PaymobSettings())
    with pytest.raises(PaymobNotConfigured):
        client.create_intention({"amount": 1})
    with pytest.raises(PaymobNotConfigured):
        client.refund(transaction_id=1, amount_cents=1)
    with pytest.raises(PaymobNotConfigured):
        client.void(transaction_id=1)
    assert rec.requests == []


def test_unconfigured_api_key_fails_before_any_bearer_request() -> None:
    settings = PaymobSettings.model_validate({"secret_key": SECRET_KEY})
    client, rec = _client({}, settings=settings)
    with pytest.raises(PaymobNotConfigured):
        client.inquire_by_order_ref("ref")
    with pytest.raises(PaymobNotConfigured):
        client.get_subscription(1)
    assert rec.requests == []


def test_inquiry_by_reference_sends_the_auth_token_in_body_and_header() -> None:
    obj = transaction_obj(merchant_order_id="ref-1")
    client, rec = _client({("POST", INQUIRY_PATH): (200, obj)})
    assert client.inquire_by_order_ref("ref-1") == obj
    assert rec.bodies("/api/auth/tokens") == [{"api_key": API_KEY}]
    assert rec.bodies(INQUIRY_PATH) == [
        {"auth_token": "auth_token_test_1", "merchant_order_id": "ref-1"}
    ]
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_inquiry_by_reference_404_means_no_transaction_yet() -> None:
    client, _ = _client({("POST", INQUIRY_PATH): (404, {"detail": "Not found."})})
    assert client.inquire_by_order_ref("ref-1") is None


def test_inquiry_by_transaction_id() -> None:
    obj = transaction_obj(txn_id=77)
    client, rec = _client({("GET", "/api/acceptance/transactions/77"): (200, obj)})
    assert client.inquire_by_transaction(77) == obj
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_inquiry_by_transaction_id_404_is_none() -> None:
    client, _ = _client(
        {("GET", "/api/acceptance/transactions/77"): (404, {"detail": "Not found."})}
    )
    assert client.inquire_by_transaction(77) is None


def test_refund_and_void_use_the_secret_key() -> None:
    client, rec = _client(
        {
            ("POST", "/api/acceptance/void_refund/refund"): (200, transaction_obj(is_refund=True)),
            ("POST", "/api/acceptance/void_refund/void"): (200, transaction_obj(is_void=True)),
        }
    )
    client.refund(transaction_id=192036465, amount_cents=4000)
    client.void(transaction_id=192036465)
    assert rec.bodies("/api/acceptance/void_refund/refund") == [
        {"transaction_id": 192036465, "amount_cents": 4000}
    ]
    assert rec.bodies("/api/acceptance/void_refund/void") == [{"transaction_id": 192036465}]
    assert all(r.headers["authorization"] == f"Token {SECRET_KEY}" for r in rec.requests)


@pytest.mark.parametrize("amount", [0, -5, 40.5, True, "4000"])
def test_refund_refuses_a_non_positive_or_non_integer_amount_without_calling(amount: Any) -> None:
    client, rec = _client({})
    with pytest.raises(ValueError, match="amount_cents"):
        client.refund(transaction_id=1, amount_cents=amount)
    assert rec.requests == []


def test_create_plan_posts_the_documented_body() -> None:
    path = "/api/acceptance/subscription-plans"
    client, rec = _client({("POST", path): (201, PLAN_RESPONSE)})
    plan = client.create_plan(
        name="Student monthly",
        frequency_days=30,
        amount_cents=9900,
        integration_id=4569877,
        webhook_url="https://lemelyig.com/api/webhooks/paymob/subscription",
        retrial_days=3,
    )
    assert plan["id"] == 1186
    assert rec.bodies(path) == [
        {
            "frequency": 30,
            "name": "Student monthly",
            "integration": 4569877,
            "amount_cents": 9900,
            "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
            "use_transaction_amount": False,
            "plan_type": "rent",
            "is_active": True,
            "number_of_deductions": None,
            "reminder_days": None,
            "retrial_days": 3,
        }
    ]
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_create_plan_refuses_an_undocumented_frequency_without_calling() -> None:
    client, rec = _client({})
    with pytest.raises(ValueError, match="frequency"):
        client.create_plan(
            name="x", frequency_days=31, amount_cents=1, integration_id=1, webhook_url="https://x.y"
        )
    assert rec.requests == []


def test_create_plan_refuses_a_non_integer_amount_without_calling() -> None:
    client, rec = _client({})
    amount: Any = 99.5
    with pytest.raises(ValueError, match="amount_cents"):
        client.create_plan(
            name="x",
            frequency_days=30,
            amount_cents=amount,
            integration_id=1,
            webhook_url="https://x.y",
        )
    assert rec.requests == []


@pytest.mark.parametrize(
    ("call", "method", "path"),
    [
        (lambda c: c.get_subscription(1264), "GET", "/api/acceptance/subscriptions/1264"),
        (
            lambda c: c.suspend_subscription(1264),
            "POST",
            "/api/acceptance/subscriptions/1264/suspend",
        ),
        (
            lambda c: c.resume_subscription(1264),
            "POST",
            "/api/acceptance/subscriptions/1264/resume",
        ),
        (
            lambda c: c.cancel_subscription(1264),
            "POST",
            "/api/acceptance/subscriptions/1264/cancel",
        ),
        (
            lambda c: c.last_transaction(1264),
            "GET",
            "/api/acceptance/subscriptions/1264/last-transaction",
        ),
    ],
)
def test_subscription_actions_hit_the_documented_paths(
    call: Callable[[PaymobClient], dict[str, Any]], method: str, path: str
) -> None:
    client, rec = _client({(method, path): (200, SUBSCRIPTION_RESPONSE)})
    assert call(client)["id"] == 1264
    assert (rec.requests[-1].method, rec.requests[-1].url.path) == (method, path)
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_update_subscription_sends_only_the_given_fields() -> None:
    path = "/api/acceptance/subscriptions/1264"
    client, rec = _client({("PUT", path): (200, SUBSCRIPTION_RESPONSE)})
    client.update_subscription(1264, amount_cents=12900)
    assert rec.bodies(path) == [{"amount_cents": 12900}]


def test_update_subscription_with_nothing_to_change_is_refused() -> None:
    client, rec = _client({})
    with pytest.raises(ValueError, match="nothing to update"):
        client.update_subscription(1264)
    assert rec.requests == []


def test_pay_with_token_sends_the_mit_body_with_no_auth_header() -> None:
    path = "/api/acceptance/payments/pay"
    client, rec = _client({("POST", path): (200, transaction_obj())})
    client.pay_with_token(card_token="tok_abc", payment_token="pk_abc")
    assert rec.bodies(path) == [
        {"source": {"identifier": "tok_abc", "subtype": "TOKEN"}, "payment_token": "pk_abc"}
    ]
    assert "authorization" not in rec.requests[-1].headers


def test_an_auth_response_without_a_token_is_a_paymob_error() -> None:
    client, rec = _client(
        {("GET", "/api/acceptance/subscriptions/1"): (200, SUBSCRIPTION_RESPONSE)}
    )
    rec.routes[AUTH] = (200, {"profile": {}})
    with pytest.raises(PaymobError, match="no token"):
        client.get_subscription(1)


# -- auth token cache ----------------------------------------------------------


def test_the_auth_token_ttl_stays_under_the_hour_paymob_grants() -> None:
    assert 0 < AUTH_TOKEN_TTL_SECONDS < 3600


def test_the_auth_token_is_cached_under_an_hour_then_renewed() -> None:
    clock = Clock()
    client, rec = _client({("POST", INQUIRY_PATH): (200, transaction_obj())}, clock=clock)
    client.inquire_by_order_ref("a")
    clock.now += 49 * 60
    client.inquire_by_order_ref("b")
    assert rec.hits("/api/auth/tokens") == 1
    clock.now += 2 * 60
    client.inquire_by_order_ref("c")
    assert rec.hits("/api/auth/tokens") == 2


def test_a_401_on_an_idempotent_get_refreshes_the_token_and_retries_once() -> None:
    path = "/api/acceptance/subscriptions/1264"
    client, rec = _client(
        {
            AUTH: [(200, {"token": "tok_old"}), (200, {"token": "tok_new"})],
            ("GET", path): [
                (401, {"detail": "incorrect credentials"}),
                (200, SUBSCRIPTION_RESPONSE),
            ],
        }
    )
    assert client.get_subscription(1264)["id"] == 1264
    gets = [r for r in rec.requests if r.url.path == path]
    assert [r.headers["authorization"] for r in gets] == ["Bearer tok_old", "Bearer tok_new"]
    assert rec.hits("/api/auth/tokens") == 2


def test_a_second_401_on_a_get_is_raised_not_retried_again() -> None:
    path = "/api/acceptance/subscriptions/1264"
    client, rec = _client({("GET", path): (401, {"detail": "incorrect credentials"})})
    with pytest.raises(PaymobError) as caught:
        client.get_subscription(1264)
    assert caught.value.status_code == 401
    assert rec.hits(path) == 2
    # The rejected token is not kept: the next call mints a fresh one.
    rec.routes[("GET", path)] = (200, SUBSCRIPTION_RESPONSE)
    assert client.get_subscription(1264)["id"] == 1264
    assert rec.hits("/api/auth/tokens") == 3


def test_a_401_on_a_bearer_post_drops_the_token_but_is_not_retried() -> None:
    path = "/api/acceptance/subscriptions/1264/cancel"
    client, rec = _client({("POST", path): [(401, {"detail": "no"}), (200, SUBSCRIPTION_RESPONSE)]})
    with pytest.raises(PaymobError) as caught:
        client.cancel_subscription(1264)
    assert caught.value.status_code == 401
    assert rec.hits(path) == 1
    assert client.cancel_subscription(1264)["id"] == 1264
    assert rec.hits("/api/auth/tokens") == 2


# -- errors --------------------------------------------------------------------


def test_an_error_status_raises_with_code_and_body_but_no_secret() -> None:
    error = {"message": "Requested Refund Amount is greater than the maximum refund amount"}
    client, _ = _client({("POST", "/api/acceptance/void_refund/refund"): (400, error)})
    with pytest.raises(PaymobError) as caught:
        client.refund(transaction_id=1, amount_cents=99999)
    assert caught.value.status_code == 400
    assert caught.value.body == error
    assert caught.value.timeout is False
    assert SECRET_KEY not in str(caught.value)


def test_a_timeout_is_flagged_so_callers_inquire_instead_of_retrying() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).create_intention({"amount": 1})
    assert caught.value.timeout is True
    assert caught.value.status_code is None


def test_a_network_failure_is_a_paymob_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).void(transaction_id=1)
    assert caught.value.timeout is False
    assert caught.value.status_code is None


def test_an_unreadable_error_body_still_raises_with_the_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"<html>bad gateway</html>")

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).void(transaction_id=1)
    assert caught.value.status_code == 502
    assert caught.value.body == {}


# -- spec §6: a charge-class call is never retried -----------------------------

#: Every non-idempotent call: (label, call, method, path). Each must hit Paymob at most once.
ONE_SHOT_CALLS: list[tuple[str, Callable[[PaymobClient], Any], str, str]] = [
    ("create_intention", lambda c: c.create_intention({"amount": 1}), "POST", "/v1/intention/"),
    (
        "refund",
        lambda c: c.refund(transaction_id=1, amount_cents=100),
        "POST",
        "/api/acceptance/void_refund/refund",
    ),
    ("void", lambda c: c.void(transaction_id=1), "POST", "/api/acceptance/void_refund/void"),
    (
        "pay_with_token",
        lambda c: c.pay_with_token(card_token="tok_abc", payment_token="pk_abc"),
        "POST",
        "/api/acceptance/payments/pay",
    ),
    (
        "create_plan",
        lambda c: c.create_plan(
            name="p",
            frequency_days=30,
            amount_cents=100,
            integration_id=1,
            webhook_url="https://x.y",
        ),
        "POST",
        "/api/acceptance/subscription-plans",
    ),
    (
        "cancel_subscription",
        lambda c: c.cancel_subscription(1),
        "POST",
        "/api/acceptance/subscriptions/1/cancel",
    ),
    (
        "suspend_subscription",
        lambda c: c.suspend_subscription(1),
        "POST",
        "/api/acceptance/subscriptions/1/suspend",
    ),
    (
        "resume_subscription",
        lambda c: c.resume_subscription(1),
        "POST",
        "/api/acceptance/subscriptions/1/resume",
    ),
    (
        "update_subscription",
        lambda c: c.update_subscription(1, amount_cents=100),
        "PUT",
        "/api/acceptance/subscriptions/1",
    ),
    ("inquire_by_order_ref", lambda c: c.inquire_by_order_ref("r"), "POST", INQUIRY_PATH),
]

CHARGE_LABELS = {"create_intention", "refund", "void", "pay_with_token"}

FAILURES: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "read_timeout": lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
    "connect_timeout": lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow", request=r)),
    "connect_error": lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)),
    "http_500": lambda r: httpx.Response(500, json={"detail": "boom"}),
    "http_502": lambda r: httpx.Response(502, content=b"bad gateway"),
    "http_503": lambda r: httpx.Response(503, json={"detail": "later"}),
    "http_401": lambda r: httpx.Response(401, json={"detail": "incorrect credentials"}),
    "read_error": lambda r: (_ for _ in ()).throw(httpx.ReadError("reset", request=r)),
    "write_error": lambda r: (_ for _ in ()).throw(httpx.WriteError("reset", request=r)),
    "protocol_error": lambda r: (_ for _ in ()).throw(httpx.RemoteProtocolError("bad", request=r)),
    "http_302": lambda r: httpx.Response(302, headers={"location": "https://elsewhere.example/"}),
    "http_200_html": lambda r: httpx.Response(
        200, content=b"<html>Down for maintenance</html>", headers={"content-type": "text/html"}
    ),
    "http_200_empty": lambda r: httpx.Response(200, content=b""),
    "http_200_array": lambda r: httpx.Response(200, json=[1, 2]),
}

#: Failures where Paymob gave no usable answer, so the call may have been applied.
UNKNOWN_OUTCOME = {
    "read_timeout",
    "connect_timeout",
    "connect_error",
    "read_error",
    "write_error",
    "protocol_error",
    "http_200_html",
    "http_200_empty",
    "http_200_array",
}


@pytest.mark.parametrize("failure", sorted(FAILURES))
@pytest.mark.parametrize(
    ("label", "call", "method", "path"), ONE_SHOT_CALLS, ids=[c[0] for c in ONE_SHOT_CALLS]
)
def test_a_failed_charge_class_call_is_sent_exactly_once(
    label: str, call: Callable[[PaymobClient], Any], method: str, path: str, failure: str
) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        seen.append((request.method, request.url.path))
        return FAILURES[failure](request)

    with pytest.raises(PaymobError) as caught:
        call(_client_with_handler(handler))
    assert seen == [(method, path)], f"{label} was sent {len(seen)} times after {failure}"
    assert caught.value.timeout is failure.endswith("timeout")
    charge_5xx = label in CHARGE_LABELS and failure.startswith("http_5")
    assert caught.value.outcome_unknown is (failure in UNKNOWN_OUTCOME or charge_5xx)
    assert (caught.value.status_code is None) is (failure in UNKNOWN_OUTCOME)


@pytest.mark.parametrize(
    "failure", ["read_timeout", "connect_error", "http_500", "http_503", "http_200_html"]
)
def test_an_idempotent_get_is_not_retried_on_a_timeout_or_server_error(failure: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        seen.append(request.url.path)
        return FAILURES[failure](request)

    client = _client_with_handler(handler)
    with pytest.raises(PaymobError):
        client.get_subscription(1)
    with pytest.raises(PaymobError):
        client.inquire_by_transaction(1)
    assert seen == ["/api/acceptance/subscriptions/1", "/api/acceptance/transactions/1"]


# -- secrets never reach error text, reprs or logs ----------------------------

CARD_TOKEN = "tok_card_secret_value"
PAYMENT_TOKEN = "pk_payment_secret_value"
AUTH_TOKEN = AUTH_TOKEN_RESPONSE["token"]


def _leaks(text: str) -> list[str]:
    secrets = (SECRET_KEY, API_KEY, AUTH_TOKEN, CARD_TOKEN, PAYMENT_TOKEN)
    return [s for s in secrets if s in text]


def _error_echoing_credentials(request: httpx.Request) -> httpx.Response:
    """A hostile/buggy Paymob reply that echoes everything it was sent."""
    sent_auth = request.headers.get("authorization", "")
    return httpx.Response(
        400,
        json={
            "detail": f"bad request: {sent_auth} {request.content.decode()}",
            "echo": {
                "authorization": sent_auth,
                "nested": [request.content.decode()],
            },
        },
    )


def test_error_text_repr_and_body_never_carry_a_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        return _error_echoing_credentials(request)

    client = _client_with_handler(handler)
    calls: list[Callable[[], Any]] = [
        lambda: client.create_intention({"amount": 1}),
        lambda: client.refund(transaction_id=1, amount_cents=100),
        lambda: client.pay_with_token(card_token=CARD_TOKEN, payment_token=PAYMENT_TOKEN),
        lambda: client.inquire_by_order_ref("ref"),
        lambda: client.get_subscription(1),
        lambda: client.cancel_subscription(1),
    ]
    for call in calls:
        with pytest.raises(PaymobError) as caught:
            call()
        error = caught.value
        assert _leaks(str(error)) == []
        assert _leaks(repr(error)) == []
        assert _leaks(json.dumps(error.body)) == []
        assert _leaks(str(error.args)) == []
    assert _leaks(caplog.text) == []


def test_a_failing_auth_call_does_not_leak_the_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": f"bad api key {request.content.decode()}"})

    client = _client_with_handler(handler)
    with pytest.raises(PaymobError) as caught:
        client.get_subscription(1)
    error = caught.value
    assert error.status_code == 400
    assert _leaks(str(error) + repr(error) + json.dumps(error.body)) == []


def test_non_secret_fields_of_an_error_body_are_kept() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"message": f"echo {SECRET_KEY}", "code": 1042, "ok": ["a", 2, None]}
        )

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).create_intention({"amount": 1})
    assert caught.value.body["code"] == 1042
    assert caught.value.body["ok"] == ["a", 2, None]
    assert SECRET_KEY not in caught.value.body["message"]


def test_header_shaped_text_is_redacted_even_for_a_credential_the_client_does_not_hold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"message": "sent Bearer someOtherLongToken123 and Token abcdefgh12345"}
        )

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).create_intention({"amount": 1})
    assert "someOtherLongToken123" not in caught.value.body["message"]
    assert "abcdefgh12345" not in caught.value.body["message"]


# -- error contract: status_code None  =>  outcome unknown ---------------------

CHARGE_CLASS: list[tuple[str, Callable[[PaymobClient], Any]]] = [
    ("create_intention", lambda c: c.create_intention({"amount": 1})),
    ("refund", lambda c: c.refund(transaction_id=1, amount_cents=100)),
    ("void", lambda c: c.void(transaction_id=1)),
    ("pay_with_token", lambda c: c.pay_with_token(card_token="t", payment_token="p")),
]


@pytest.mark.parametrize(("label", "call"), CHARGE_CLASS, ids=[c[0] for c in CHARGE_CLASS])
@pytest.mark.parametrize("failure", ["http_200_html", "http_200_empty", "http_200_array"])
def test_an_unreadable_2xx_on_a_charge_class_call_is_unknown_not_a_decline(
    label: str, call: Callable[[PaymobClient], Any], failure: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        return FAILURES[failure](request)

    with pytest.raises(PaymobError) as caught:
        call(_client_with_handler(handler))
    error = caught.value
    assert error.status_code is None
    assert error.outcome_unknown is True
    assert error.timeout is False
    assert error.body == {}


def test_an_empty_2xx_is_not_turned_into_an_empty_dict_on_any_call() -> None:
    client = _client_with_handler(lambda r: FAILURES["http_200_empty"](r))
    for call in (
        lambda: client.cancel_subscription(1),
        lambda: client.update_subscription(1, amount_cents=5),
        lambda: client.get_subscription(1),
    ):
        with pytest.raises(PaymobError) as caught:
            call()
        assert caught.value.outcome_unknown is True


def test_an_empty_json_object_2xx_is_a_valid_answer() -> None:
    client, _ = _client({("POST", "/api/acceptance/subscriptions/1/cancel"): (200, {})})
    assert client.cancel_subscription(1) == {}


def test_a_received_error_status_is_a_known_outcome() -> None:
    client, _ = _client(
        {("POST", "/api/acceptance/void_refund/void"): (400, {"message": "settled"})}
    )
    with pytest.raises(PaymobError) as caught:
        client.void(transaction_id=1)
    assert caught.value.status_code == 400
    assert caught.value.outcome_unknown is False


def test_not_configured_means_nothing_was_sent() -> None:
    client, rec = _client({}, settings=PaymobSettings())
    with pytest.raises(PaymobNotConfigured) as caught:
        client.create_intention({"amount": 1})
    assert caught.value.outcome_unknown is False
    assert caught.value.status_code is None
    assert rec.requests == []


# -- the token lock, token scrubbing and key scrubbing -------------------------


def test_two_threads_racing_for_a_token_mint_it_once() -> None:
    mints: list[int] = []
    barrier = threading.Barrier(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            mints.append(1)
            time.sleep(0.15)  # hold the mint open so the second thread arrives mid-flight
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        return httpx.Response(200, json=SUBSCRIPTION_RESPONSE)

    client = _client_with_handler(handler)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            client.get_subscription(1264)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert len(mints) == 1


def test_a_401_echoing_the_rejected_token_does_not_leak_it() -> None:
    def make() -> tuple[PaymobClient, list[str]]:
        minted = iter(["tok_rejected_one", "tok_rejected_two"])
        issued: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/tokens":
                token = next(minted)
                issued.append(token)
                return httpx.Response(200, json={"token": token})
            # The bare token, so only value-based scrubbing (not the header-shape regex) catches it.
            bare = request.headers["authorization"].removeprefix("Bearer ")
            return httpx.Response(401, json={"detail": f"rejected:{bare}"})

        return _client_with_handler(handler), issued

    client, issued = make()
    with pytest.raises(PaymobError) as caught:
        client.get_subscription(1)
    assert issued == ["tok_rejected_one", "tok_rejected_two"]
    text = str(caught.value) + repr(caught.value) + json.dumps(caught.value.body)
    assert not any(token in text for token in issued)
    assert caught.value.body["detail"] == "rejected:[redacted]"

    client, issued = make()
    with pytest.raises(PaymobError) as caught:
        client.cancel_subscription(1)
    text = str(caught.value) + repr(caught.value) + json.dumps(caught.value.body)
    assert not any(token in text for token in issued)


def test_a_credential_in_an_error_body_key_is_scrubbed_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={f"echo_{SECRET_KEY}": {f"inner_{SECRET_KEY}": "x"}})

    with pytest.raises(PaymobError) as caught:
        _client_with_handler(handler).create_intention({"amount": 1})
    assert SECRET_KEY not in json.dumps(caught.value.body)
    assert caught.value.body


def test_forgetting_a_rejected_token_leaves_a_newer_cached_token_alone() -> None:
    holder: dict[str, PaymobClient] = {}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json={"token": "tok_stale"})
        seen.append(request.headers["authorization"])
        if len(seen) == 1:
            # Another thread refreshed the cache while our request was in flight.
            holder["c"]._token = "tok_fresh"
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json=SUBSCRIPTION_RESPONSE)

    client = _client_with_handler(handler)
    holder["c"] = client
    assert client.get_subscription(1264)["id"] == 1264
    assert seen == ["Bearer tok_stale", "Bearer tok_fresh"]


# -- a 5xx is "unknown" only for charge-class calls -----------------------------

OTHER_CALLS: list[tuple[str, Callable[[PaymobClient], Any]]] = [
    (
        "create_plan",
        lambda c: c.create_plan(
            name="p",
            frequency_days=30,
            amount_cents=100,
            integration_id=1,
            webhook_url="https://x.y",
        ),
    ),
    ("get_subscription", lambda c: c.get_subscription(1)),
    ("update_subscription", lambda c: c.update_subscription(1, amount_cents=100)),
    ("suspend_subscription", lambda c: c.suspend_subscription(1)),
    ("resume_subscription", lambda c: c.resume_subscription(1)),
    ("cancel_subscription", lambda c: c.cancel_subscription(1)),
    ("last_transaction", lambda c: c.last_transaction(1)),
    ("inquire_by_transaction", lambda c: c.inquire_by_transaction(1)),
    ("inquire_by_order_ref", lambda c: c.inquire_by_order_ref("r")),
]


def _failing_with(status: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        return httpx.Response(status, json={"detail": "gateway"})

    return handler


@pytest.mark.parametrize("status", [500, 502, 503, 504])
@pytest.mark.parametrize(("label", "call"), CHARGE_CLASS, ids=[c[0] for c in CHARGE_CLASS])
def test_a_5xx_on_a_charge_class_call_is_outcome_unknown_with_the_status_kept(
    label: str, call: Callable[[PaymobClient], Any], status: int
) -> None:
    with pytest.raises(PaymobError) as caught:
        call(_client_with_handler(_failing_with(status)))
    assert caught.value.status_code == status
    assert caught.value.outcome_unknown is True


@pytest.mark.parametrize("status", [500, 503])
@pytest.mark.parametrize(("label", "call"), OTHER_CALLS, ids=[c[0] for c in OTHER_CALLS])
def test_a_5xx_on_any_other_call_is_a_known_outcome(
    label: str, call: Callable[[PaymobClient], Any], status: int
) -> None:
    with pytest.raises(PaymobError) as caught:
        call(_client_with_handler(_failing_with(status)))
    assert caught.value.status_code == status
    assert caught.value.outcome_unknown is False


@pytest.mark.parametrize(("label", "call"), CHARGE_CLASS, ids=[c[0] for c in CHARGE_CLASS])
def test_a_4xx_on_a_charge_class_call_stays_a_known_decline(
    label: str, call: Callable[[PaymobClient], Any]
) -> None:
    with pytest.raises(PaymobError) as caught:
        call(_client_with_handler(_failing_with(400)))
    assert caught.value.status_code == 400
    assert caught.value.outcome_unknown is False
