"""HTTP-boundary tests for ``POST /api/client-errors`` (PR 1 chunk C).

Hermetic throughout: no database, no Gemini, no real clock — every rate-limit
test drives a :class:`~lemely.web.deps.ClientErrorLimiters` built on an
injected fake clock (mirroring the cooldown-store tests' own convention for
:class:`~lemely.auth.cooldown.CooldownStore`), so nothing here sleeps out a
real 60-second window.

``tests/test_authz_matrix_complete.py`` is the exhaustive, generated proof
that this route carries no auth guard at all (``PUBLIC``); this file proves
the route's own behaviour — acceptance, DTO validation, the two rate
limiters, the oversized-body 413, and the structured log line it emits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from lemely.web.app import create_app
from lemely.web.deps import ClientErrorLimiters, get_client_error_limiters, reset_singletons
from lemely.web.ratelimit import SlidingWindowLimiter

if TYPE_CHECKING:
    from collections.abc import Iterator


class FakeClock:
    """A settable clock for :class:`SlidingWindowLimiter`.

    Starts at an arbitrary large value (not 0) so ``now - window_seconds``
    never goes negative in a test — a stand-in for "some time after process
    start", mirroring how ``time.monotonic`` behaves in production.
    """

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _limiters(
    clock: FakeClock, *, per_client: int = 10, global_limit: int = 300
) -> ClientErrorLimiters:
    return ClientErrorLimiters(
        per_client=SlidingWindowLimiter(limit=per_client, window_seconds=60.0, clock=clock),
        global_=SlidingWindowLimiter(limit=global_limit, window_seconds=60.0, clock=clock),
    )


def _valid_report(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "message": "Something broke",
        "route": "/student/overview",
        "buildId": "build-123",
        "kind": "unhandled",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> Iterator[TestClient]:
    """A hermetic client wired to the real limiter mechanism on a fake clock.

    Built once and returned by the override, not built fresh inside the
    override lambda — FastAPI calls a dependency override on every request,
    so a lambda that constructed new (and therefore always-empty)
    ``SlidingWindowLimiter`` instances per call would never actually
    accumulate events across requests.
    """
    app = create_app()
    limiters = _limiters(clock)
    app.dependency_overrides[get_client_error_limiters] = lambda: limiters
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


# ── Acceptance and validation ──────────────────────────────────────────────


def test_accepts_minimal_anonymous_report(client: TestClient) -> None:
    """No auth header at all — this route must still work for a signed-out crash."""
    resp = client.post("/api/client-errors", json=_valid_report())
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"accepted": True}


def test_rejects_oversized_message(client: TestClient) -> None:
    resp = client.post("/api/client-errors", json=_valid_report(message="x" * 2001))
    assert resp.status_code == 422, resp.text


def test_rejects_extra_fields(client: TestClient) -> None:
    """``ApiModel``'s ``extra=\"forbid\"`` — a mass-assignment hole otherwise."""
    resp = client.post("/api/client-errors", json=_valid_report(somethingUnexpected="nope"))
    assert resp.status_code == 422, resp.text


def test_rejects_bad_kind(client: TestClient) -> None:
    resp = client.post("/api/client-errors", json=_valid_report(kind="not-a-real-kind"))
    assert resp.status_code == 422, resp.text


# ── Size cap ────────────────────────────────────────────────────────────────


def test_413_on_oversized_content_length(client: TestClient) -> None:
    """A declared ``Content-Length`` over 32 KiB is rejected before parsing.

    The oversized field here (``message``) would also fail DTO validation on
    its own (max 2000 chars) — the point of this test is that the response is
    **413**, not 422, proving the size guard runs first.
    """
    resp = client.post("/api/client-errors", json=_valid_report(message="x" * 40_000))
    assert resp.status_code == 413, resp.text


# ── Per-client rate limit ───────────────────────────────────────────────────


def test_per_client_limit_is_429_with_retry_after_a_different_ip_is_unaffected(
    client: TestClient,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.5"}
    for i in range(10):
        resp = client.post("/api/client-errors", json=_valid_report(), headers=headers)
        assert resp.status_code == 202, (i, resp.text)

    eleventh = client.post("/api/client-errors", json=_valid_report(), headers=headers)
    assert eleventh.status_code == 429, eleventh.text
    assert int(eleventh.headers["Retry-After"]) > 0

    other_ip = client.post(
        "/api/client-errors",
        json=_valid_report(),
        headers={"X-Forwarded-For": "198.51.100.9"},
    )
    assert other_ip.status_code == 202, other_ip.text


# ── Global rate limit ───────────────────────────────────────────────────────


def test_global_limit_is_429_across_distinct_clients(clock: FakeClock) -> None:
    """Several distinct IPs, each well under its own per-client cap, can still
    trip the shared global limiter.

    Wired with a deliberately small ``global_limit`` (2) rather than the
    production 300 — the mechanism being proven (a shared bucket every caller
    draws from) does not depend on the exact number, and a small one keeps
    this test to three requests instead of three hundred.
    """
    app = create_app()
    limiters = _limiters(clock, per_client=10, global_limit=2)
    app.dependency_overrides[get_client_error_limiters] = lambda: limiters
    test_client = TestClient(app)
    try:
        first = test_client.post(
            "/api/client-errors", json=_valid_report(), headers={"X-Forwarded-For": "10.0.0.1"}
        )
        second = test_client.post(
            "/api/client-errors", json=_valid_report(), headers={"X-Forwarded-For": "10.0.0.2"}
        )
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text

        third = test_client.post(
            "/api/client-errors", json=_valid_report(), headers={"X-Forwarded-For": "10.0.0.3"}
        )
        assert third.status_code == 429, third.text
        assert int(third.headers["Retry-After"]) > 0
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


# ── The structured log line ─────────────────────────────────────────────────


def test_accepted_report_emits_the_expected_structured_log(client: TestClient) -> None:
    with structlog.testing.capture_logs() as captured:
        resp = client.post(
            "/api/client-errors",
            json=_valid_report(
                stack="Error: boom\n  at x",
                componentStack="in Widget",
                userAgent="TestAgent/1.0",
                occurredAt="2026-09-02T12:00:00Z",
            ),
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
    assert resp.status_code == 202, resp.text

    events = [entry for entry in captured if entry.get("event") == "client_error"]
    assert len(events) == 1, captured
    entry = events[0]
    assert entry["log_level"] == "warning"
    assert entry["kind"] == "unhandled"
    assert entry["message"] == "Something broke"
    assert entry["route"] == "/student/overview"
    assert entry["build_id"] == "build-123"
    assert entry["client_ip"] == "203.0.113.99"
    assert entry["user_agent"] == "TestAgent/1.0"
    assert entry["occurred_at"] == "2026-09-02T12:00:00+00:00"
    assert entry["stack"] == "Error: boom\n  at x"
    assert entry["component_stack"] == "in Widget"


def test_rejected_report_emits_no_log(client: TestClient) -> None:
    """A body that fails validation must never reach the log sink."""
    with structlog.testing.capture_logs() as captured:
        resp = client.post("/api/client-errors", json=_valid_report(kind="not-a-real-kind"))
    assert resp.status_code == 422, resp.text
    assert [e for e in captured if e.get("event") == "client_error"] == []


# ── deps.py wiring sanity ───────────────────────────────────────────────────


def test_reset_singletons_clears_the_client_error_limiters() -> None:
    get_client_error_limiters()
    assert get_client_error_limiters.cache_info().currsize == 1

    reset_singletons()

    assert get_client_error_limiters.cache_info().currsize == 0
