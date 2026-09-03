"""The engine must bound how long a connect can block.

libpq's own ``connect_timeout`` default is unlimited. That is a defensible
default for a CLI and the wrong one for a server: an outage that *drops*
packets rather than refusing them (a firewall or security-group change, a
pooler that accepts and stalls) leaves every connect blocked on the OS TCP
timeout, which is minutes.

That became load-bearing when ``GET /api/health`` started reading
``component_thresholds`` to report ``gradeBoundariesLoaded``. ``health`` is a
sync route, so Starlette runs it in a bounded threadpool -- a liveness probe
polling an unreachable database would hold one worker per poll for the full
TCP timeout and eventually starve every other route. The endpoint added to
make an outage *diagnosable* would have amplified it.

10.255.255.1 is an RFC 1918 address that is not routed here, so a SYN to it is
dropped rather than refused -- which is exactly the shape that hangs. A test
that merely asserts "an exception was raised" would pass against a refused
connection while the real bug persisted, so these assert on *elapsed time*.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import SQLAlchemyError

from lemely.db.session import _build_engine, _connect_args
from lemely.runtime.config import DatabaseSettings

# A SYN here is dropped, not answered: the failure mode this test exists for.
_BLACKHOLE_URL = "postgresql+psycopg://u:p@10.255.255.1:5432/d"


def test_connect_to_a_blackholed_host_fails_fast_rather_than_hanging() -> None:
    """A dropped-packet database outage must fail in seconds, not minutes."""
    cfg = DatabaseSettings(url=_BLACKHOLE_URL, connect_timeout_seconds=2, pool_pre_ping=False)
    engine = _build_engine(cfg)

    start = time.monotonic()
    with pytest.raises(SQLAlchemyError):
        engine.connect()
    elapsed = time.monotonic() - start

    # Generous headroom over the 2s setting -- the assertion is "bounded",
    # not "precise". Without connect_timeout this runs into the minutes.
    assert elapsed < 15, f"connect blocked for {elapsed:.1f}s; connect_timeout is not being applied"


def test_connect_timeout_is_only_passed_to_postgres_drivers() -> None:
    """``connect_timeout`` is a libpq parameter.

    Passing it to a driver that does not know it fails at connect time, so it
    must not be attached to a non-Postgres URL.
    """
    assert _connect_args(DatabaseSettings(url="postgresql+psycopg://u:p@h/d")) == {
        "connect_timeout": 5
    }
    assert _connect_args(DatabaseSettings(url="sqlite:///:memory:")) == {}
