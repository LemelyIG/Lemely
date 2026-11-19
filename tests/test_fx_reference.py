"""Market USD to EGP reference (P08-T21): failures are `None`, the caches hold, nothing raises.

The HTTP layer is ``httpx.MockTransport``; the clock is a fake, so no test touches the network or
sleeps.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest

from lemely.io import fx_reference
from lemely.io.fx_reference import FxReference, get_usd_egp_reference

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: 2026-11-16 00:02:31 UTC, the unix stamp the live feed carried when the shape was checked.
STAMP = 1794787351


def _body(rate: object = 53.741239, stamp: object = STAMP, **extra: object) -> dict[str, object]:
    rates: dict[str, object] = {"USD": 1, "EUR": 0.86}
    if rate is not None:
        rates["EGP"] = rate
    return {
        "result": "success",
        "time_last_update_unix": stamp,
        "base_code": "USD",
        "rates": rates,
        **extra,
    }


class Feed:
    """A MockTransport handler that counts calls and replays one scripted reply."""

    def __init__(self, reply: Callable[[httpx.Request], httpx.Response]) -> None:
        self.reply = reply
        self.calls = 0
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.urls.append(str(request.url))
        return self.reply(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _ok(body: dict[str, object] | None = None) -> Feed:
    return Feed(lambda _r: httpx.Response(200, json=body if body is not None else _body()))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fx_reference.clear_cache()
    yield
    fx_reference.clear_cache()


def test_success_reads_rate_source_and_the_update_date() -> None:
    feed = _ok()
    got = get_usd_egp_reference(client=feed.client())
    assert got == FxReference(
        rate=Decimal("53.741239"), source="open.er-api.com", as_of=date(2026, 11, 16)
    )
    assert feed.urls == ["https://open.er-api.com/v6/latest/USD"]


def test_the_rate_is_an_exact_decimal_not_a_float_artefact() -> None:
    got = get_usd_egp_reference(client=_ok(_body(rate=50.1)).client())
    assert got is not None
    assert got.rate == Decimal("50.1")


def _raise(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def reply(_request: httpx.Request) -> httpx.Response:
        raise exc

    return reply


@pytest.mark.parametrize(
    "feed",
    [
        pytest.param(Feed(_raise(httpx.ReadTimeout("slow"))), id="timeout"),
        pytest.param(Feed(_raise(httpx.ConnectError("down"))), id="connect-error"),
        pytest.param(Feed(lambda _r: httpx.Response(429, text="slow down")), id="http-429"),
        pytest.param(Feed(lambda _r: httpx.Response(500, json=_body())), id="http-500"),
        pytest.param(Feed(lambda _r: httpx.Response(200, text="<html>")), id="not-json"),
        pytest.param(Feed(lambda _r: httpx.Response(200, json=[1, 2])), id="not-an-object"),
        pytest.param(_ok(_body(rate=None)), id="missing-egp"),
        pytest.param(_ok(_body(rate="abc")), id="rate-not-numeric"),
        pytest.param(_ok(_body(rate=True)), id="rate-is-a-bool"),
        pytest.param(_ok(_body(rate=0)), id="rate-zero"),
        pytest.param(_ok(_body(rate=-3)), id="rate-negative"),
        pytest.param(_ok(_body(rate=0.99)), id="below-band"),
        pytest.param(_ok(_body(rate=1000.5)), id="above-band"),
        pytest.param(_ok(_body(rate="NaN")), id="nan"),
        pytest.param(_ok(_body(rate="Infinity")), id="infinity"),
        pytest.param(_ok(_body(stamp=None)), id="missing-stamp"),
        pytest.param(_ok(_body(stamp="yesterday")), id="stamp-not-int"),
        pytest.param(_ok(_body(stamp=10**30)), id="stamp-out-of-range"),
        pytest.param(_ok({**_body(), "result": "error"}), id="result-not-success"),
    ],
)
def test_any_failure_is_none_and_logs_one_warning(
    feed: Feed, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="lemely.io.fx_reference"):
        assert get_usd_egp_reference(client=feed.client()) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_the_band_edges_are_accepted() -> None:
    for edge in ("1", "1000"):
        fx_reference.clear_cache()
        got = get_usd_egp_reference(client=_ok(_body(rate=edge)).client())
        assert got is not None
        assert got.rate == Decimal(edge)


def test_a_success_is_cached_for_24_hours_then_refetched() -> None:
    clock = Clock()
    feed = _ok()
    client = feed.client()
    first = get_usd_egp_reference(client=client, clock=clock)
    clock.now += 24 * 3600 - 1
    assert get_usd_egp_reference(client=client, clock=clock) == first
    assert feed.calls == 1
    clock.now += 2
    assert get_usd_egp_reference(client=client, clock=clock) == first
    assert feed.calls == 2


def test_a_failure_is_cached_for_ten_minutes_then_retried() -> None:
    clock = Clock()
    replies = iter([httpx.Response(503), httpx.Response(200, json=_body())])
    feed = Feed(lambda _r: next(replies))
    client = feed.client()
    assert get_usd_egp_reference(client=client, clock=clock) is None
    clock.now += 10 * 60 - 1
    assert get_usd_egp_reference(client=client, clock=clock) is None
    assert feed.calls == 1  # no hammering while the negative cache holds
    clock.now += 2
    assert get_usd_egp_reference(client=client, clock=clock) is not None
    assert feed.calls == 2


def test_a_second_failure_inside_the_negative_window_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    client = Feed(lambda _r: httpx.Response(503)).client()
    with caplog.at_level(logging.WARNING, logger="lemely.io.fx_reference"):
        for _ in range(5):
            assert get_usd_egp_reference(client=client, clock=clock) is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_the_request_carries_a_two_second_timeout() -> None:
    seen: list[dict[str, float | None]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.extensions["timeout"]))
        return httpx.Response(200, json=_body())

    get_usd_egp_reference(client=Feed(reply).client())
    assert seen == [{"connect": 2.0, "read": 2.0, "write": 2.0, "pool": 2.0}]


def test_the_owned_client_is_built_with_the_two_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[object] = []
    real = httpx.Client

    def factory(*args: object, **kwargs: object) -> httpx.Client:
        built.append(kwargs.get("timeout"))
        return real(transport=httpx.MockTransport(_ok()), **{})

    monkeypatch.setattr(httpx, "Client", factory)
    assert get_usd_egp_reference() is not None
    assert built == [2.0]


def test_a_429_is_negative_cached_for_twenty_minutes() -> None:
    clock = Clock()
    replies = iter([httpx.Response(429), httpx.Response(200, json=_body())])
    feed = Feed(lambda _r: next(replies))
    client = feed.client()
    assert get_usd_egp_reference(client=client, clock=clock) is None
    clock.now += 20 * 60 - 1
    assert get_usd_egp_reference(client=client, clock=clock) is None
    assert feed.calls == 1  # still inside the feed's own 20 minute ban
    clock.now += 2
    assert get_usd_egp_reference(client=client, clock=clock) is not None
    assert feed.calls == 2


def test_other_failures_still_retry_after_ten_minutes() -> None:
    clock = Clock()
    feed = Feed(lambda _r: httpx.Response(503))
    client = feed.client()
    get_usd_egp_reference(client=client, clock=clock)
    clock.now += 10 * 60 + 1
    get_usd_egp_reference(client=client, clock=clock)
    assert feed.calls == 2


def test_the_deadline_is_two_seconds_of_wall_clock() -> None:
    assert fx_reference.DEADLINE_SECONDS == 2.0


def test_a_feed_that_stalls_is_abandoned_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(fx_reference, "DEADLINE_SECONDS", 0.2)
    release = threading.Event()

    def stall(_request: httpx.Request) -> httpx.Response:
        release.wait(10)  # slower than the deadline, faster than the test's patience
        return httpx.Response(200, json=_body())

    clock = Clock()
    client = Feed(stall).client()
    started = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING, logger="lemely.io.fx_reference"):
            assert get_usd_egp_reference(client=client, clock=clock) is None
        elapsed = time.monotonic() - started
        assert elapsed < 1.0
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
        # the stall is negative cached: the next call does not wait again
        again = time.monotonic()
        assert get_usd_egp_reference(client=client, clock=clock) is None
        assert time.monotonic() - again < 0.1
    finally:
        release.set()


def test_a_slow_but_in_time_answer_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_reference, "DEADLINE_SECONDS", 2.0)

    def slowish(_request: httpx.Request) -> httpx.Response:
        time.sleep(0.1)
        return httpx.Response(200, json=_body())

    assert get_usd_egp_reference(client=Feed(slowish).client()) is not None


def test_concurrent_cold_requests_share_one_fetch() -> None:
    first_in_feed = threading.Event()
    second_in_feed = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    results: list[FxReference | None] = []

    def request(_request: httpx.Request) -> httpx.Response:
        if first_in_feed.is_set():
            second_in_feed.set()
        first_in_feed.set()
        assert release.wait(5)
        return httpx.Response(200, json=_body())

    def read() -> None:
        results.append(get_usd_egp_reference(client=client))

    def read_second() -> None:
        second_started.set()
        read()

    with Feed(request).client() as client:
        first = threading.Thread(target=read)
        second = threading.Thread(target=read_second)
        first.start()
        try:
            assert first_in_feed.wait(1)
            second.start()
            assert second_started.wait(1)
            assert not second_in_feed.wait(0.25)
        finally:
            release.set()
            first.join(5)
            if second.ident is not None:
                second.join(5)
    assert len(results) == 2 and results[0] is not None and results[0] == results[1]


def test_redirect_is_refused_even_when_client_follows_redirects() -> None:
    def request(req: httpx.Request) -> httpx.Response:
        if req.url.host == "open.er-api.com":
            return httpx.Response(302, headers={"location": "https://redirect.invalid/"})
        return httpx.Response(200, json=_body())

    feed = Feed(request)
    with httpx.Client(transport=httpx.MockTransport(feed), follow_redirects=True) as client:
        assert get_usd_egp_reference(client=client) is None
    assert feed.calls == 1


def test_fetch_runs_on_daemon_thread() -> None:
    workers: list[threading.Thread] = []

    def request(_request: httpx.Request) -> httpx.Response:
        workers.append(threading.current_thread())
        return httpx.Response(200, json=_body())

    with Feed(request).client() as client:
        assert get_usd_egp_reference(client=client) is not None
    assert [worker.daemon for worker in workers] == [True]


def test_late_failure_does_not_emit_a_second_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(fx_reference, "DEADLINE_SECONDS", 0.2)
    release = threading.Event()
    workers: list[threading.Thread] = []

    def request(_request: httpx.Request) -> httpx.Response:
        workers.append(threading.current_thread())
        assert release.wait(5)
        raise httpx.ReadTimeout("late read timeout")

    with Feed(request).client() as client:
        try:
            assert get_usd_egp_reference(client=client) is None
        finally:
            release.set()
            for worker in workers:
                worker.join(5)
    assert len(workers) == 1 and not workers[0].is_alive()
    warnings = [r.message for r in caplog.records if r.name == fx_reference.__name__]
    assert warnings == ["fx reference: no answer within 0.2 s from open.er-api.com"]


def test_an_unexpected_transport_error_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with Feed(_raise(RuntimeError("unexpected"))).client() as client:
        assert get_usd_egp_reference(client=client) is None
    assert "unexpected RuntimeError" in caplog.text


def test_an_oversized_stream_is_cut_off(caplog: pytest.LogCaptureFixture) -> None:
    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b" " * (64 * 1024)
            yield b" "
            pytest.fail("the worker read beyond the response size cap")

    feed = Feed(lambda _r: httpx.Response(200, stream=Stream()))
    with feed.client() as client:
        assert get_usd_egp_reference(client=client) is None
    assert "body over 65536 bytes" in caplog.text


def test_default_transport_cannot_reach_the_fx_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpcore

    def network_attempt(_pool: httpcore.ConnectionPool, _request: httpcore.Request) -> None:
        pytest.fail("the default transport tried to send the FX request")

    monkeypatch.setattr(httpcore.ConnectionPool, "handle_request", network_attempt)
    with httpx.Client(trust_env=False) as client:
        assert client.get(fx_reference.SOURCE_URL).status_code == 503
