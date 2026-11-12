"""HTTP-boundary tests for ``POST /api/contact`` (landing-page FAQ composer).

Hermetic: a ``FakeEmailProvider`` stands in for Resend and every rate-limit test
uses :class:`~lemely.web.deps.ContactLimiters` on an injected fake clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.web.app import create_app
from lemely.web.deps import (
    ContactLimiters,
    get_contact_limiters,
    get_email_provider,
    reset_singletons,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from tests.auth_fakes import FakeEmailProvider

if TYPE_CHECKING:
    from collections.abc import Iterator


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _limiters(clock: FakeClock, *, per_client: int = 3, global_limit: int = 60) -> ContactLimiters:
    return ContactLimiters(
        per_client=SlidingWindowLimiter(limit=per_client, window_seconds=600.0, clock=clock),
        global_=SlidingWindowLimiter(limit=global_limit, window_seconds=86400.0, clock=clock),
    )


@pytest.fixture
def provider() -> FakeEmailProvider:
    return FakeEmailProvider()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(provider: FakeEmailProvider, clock: FakeClock) -> Iterator[TestClient]:
    reset_singletons()
    app = create_app()
    app.dependency_overrides[get_email_provider] = lambda: provider
    limiters = _limiters(clock)
    app.dependency_overrides[get_contact_limiters] = lambda: limiters
    with TestClient(app) as test_client:
        yield test_client
    reset_singletons()


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"email": "visitor@example.com", "message": "How does marking work?"}
    body.update(overrides)
    return body


def test_accepts_and_forwards_the_exact_email_and_message(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    response = client.post("/api/contact", json=_body())
    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert provider.sent_contact_messages == [("visitor@example.com", "How does marking work?")]


def test_message_is_stripped_before_sending(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    assert client.post("/api/contact", json=_body(message="  hi there \n")).status_code == 202
    assert provider.sent_contact_messages[0][1] == "hi there"


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"email": "a@example.com\r\nBcc: x@example.com"},
        {"email": "a b@example.com"},
        {"email": "a" * 250 + "@example.com"},
        {"message": ""},
        {"message": "   \n\t "},
        {"message": "x" * 2001},
        {"extra": "field"},
    ],
)
def test_invalid_bodies_are_422_and_send_nothing(
    client: TestClient, provider: FakeEmailProvider, overrides: dict[str, object]
) -> None:
    assert client.post("/api/contact", json=_body(**overrides)).status_code == 422
    assert provider.sent_contact_messages == []


def test_oversized_declared_body_is_413(client: TestClient, provider: FakeEmailProvider) -> None:
    response = client.post(
        "/api/contact",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(9 * 1024)},
    )
    assert response.status_code == 413
    assert provider.sent_contact_messages == []


def test_per_ip_limit_returns_429_with_retry_after(
    client: TestClient, provider: FakeEmailProvider, clock: FakeClock
) -> None:
    headers = {"x-forwarded-for": "203.0.113.7"}
    for _ in range(3):
        assert client.post("/api/contact", json=_body(), headers=headers).status_code == 202
    blocked = client.post("/api/contact", json=_body(), headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert len(provider.sent_contact_messages) == 3

    # Another address is unaffected, and the first recovers once the window passes.
    assert (
        client.post(
            "/api/contact", json=_body(), headers={"x-forwarded-for": "198.51.100.9"}
        ).status_code
        == 202
    )
    clock.advance(601)
    assert client.post("/api/contact", json=_body(), headers=headers).status_code == 202


def test_global_limit_returns_429() -> None:
    reset_singletons()
    clock = FakeClock()
    provider = FakeEmailProvider()
    app = create_app()
    app.dependency_overrides[get_email_provider] = lambda: provider
    limiters = _limiters(clock, per_client=100, global_limit=2)
    app.dependency_overrides[get_contact_limiters] = lambda: limiters
    with TestClient(app) as client:
        for i in range(2):
            headers = {"x-forwarded-for": f"203.0.113.{i}"}
            assert client.post("/api/contact", json=_body(), headers=headers).status_code == 202
        blocked = client.post(
            "/api/contact", json=_body(), headers={"x-forwarded-for": "203.0.113.99"}
        )
    reset_singletons()
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_provider_failure_is_502_and_leaks_nothing(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    provider.raise_on_send = True
    response = client.post("/api/contact", json=_body(message="super private question"))
    assert response.status_code == 502
    assert response.json() == {
        "detail": "Could not send your message. Please email contact@lemelyig.com."
    }
    assert "super private question" not in response.text
    assert "visitor@example.com" not in response.text
