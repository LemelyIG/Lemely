"""Engine and session management for the application database.

Provides a lazily-constructed, process-wide SQLAlchemy :class:`Engine` and
``sessionmaker`` derived from :class:`~lemely.runtime.config.DatabaseSettings`,
plus a :func:`session_scope` context manager with commit/rollback semantics.

Synchronous SQLAlchemy 2.0 is used deliberately: the rest of the codebase (CLI,
Gradio, FastAPI sync routes) is synchronous, and FastAPI runs sync dependencies
in a threadpool. This keeps the data layer simple and consistent.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from lemely.runtime.config import DatabaseSettings, Settings, load_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None
_engine_url: str | None = None


def _connect_args(cfg: DatabaseSettings) -> dict[str, object]:
    """Driver-specific connect keywords.

    These are all libpq parameters, so they are passed only for the Postgres
    dialects that understand them -- another driver would reject the unknown
    keywords at connect time. See :class:`DatabaseSettings` for why an
    unbounded connect is the wrong default for a server process.

    ``connect_timeout`` bounds *establishment only*. With ``pool_pre_ping``
    on, every checkout of an already-open pooled connection first issues
    ``SELECT 1``, and that is a read on an established socket -- a different
    failure to bound. The keepalive keywords cover it for the outage this is
    actually written for: when a firewall or security-group change starts
    dropping packets, the peer stops ACKing, and ``tcp_user_timeout`` fails
    the socket after that many milliseconds instead of letting the kernel
    retry for minutes.

    What this does **not** cover: a middlebox that completes the handshake,
    ACKs at the TCP layer, and then never relays anything. The kernel sees a
    healthy link, so no client-side timeout fires and a pre-ping blocks
    indefinitely. Bounding that needs a read deadline libpq does not expose.
    It is a narrower shape than the packet-drop case and is called out here so
    the next reader does not assume the pooled path is fully bounded.

    ``tcp_user_timeout`` needs libpq >= 12 and a platform with
    ``TCP_USER_TIMEOUT``; where the socket option is missing (macOS, Windows)
    libpq ignores it rather than failing the connect, so a developer on such a
    machine loses the bound but not the connection. CI and the deploy target
    are both Linux, which is where the bound has to hold.
    """
    if not cfg.url.startswith("postgres"):
        return {}
    return {
        "connect_timeout": cfg.connect_timeout_seconds,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 5,
        "keepalives_count": 3,
        "tcp_user_timeout": cfg.connect_timeout_seconds * 1000,
    }


def _build_engine(cfg: DatabaseSettings) -> Engine:
    return create_engine(
        cfg.url,
        echo=cfg.echo,
        pool_size=cfg.pool_size,
        max_overflow=cfg.max_overflow,
        pool_pre_ping=cfg.pool_pre_ping,
        pool_timeout=cfg.pool_timeout_seconds,
        connect_args=_connect_args(cfg),
        future=True,
    )


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the process-wide :class:`Engine`, building it on first use.

    If ``settings`` is provided and its database URL differs from the cached
    engine's, the engine is rebuilt (used by tests that point at a temp DB).
    """
    global _engine, _sessionmaker, _engine_url
    cfg = (settings or load_settings()).database
    if _engine is None or _engine_url != cfg.url:
        if _engine is not None:
            _engine.dispose()
        _engine = _build_engine(cfg)
        _sessionmaker = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        _engine_url = cfg.url
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    """Return the process-wide ``sessionmaker`` bound to the engine."""
    get_engine(settings)
    assert _sessionmaker is not None  # noqa: S101 - set by get_engine
    return _sessionmaker


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Yield a transactional :class:`Session`, committing on success.

    Rolls back and re-raises on any exception; always closes the session.
    """
    factory = get_sessionmaker(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose the cached engine and reset module state (used by tests)."""
    global _engine, _sessionmaker, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
    _engine_url = None
