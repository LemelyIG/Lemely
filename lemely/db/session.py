"""Engine and session management for the application database.

Provides a lazily-constructed, process-wide SQLAlchemy :class:`Engine` and
``sessionmaker`` derived from :class:`~lemely.runtime.config.DatabaseSettings`,
plus a :func:`session_scope` context manager with commit/rollback semantics.

Synchronous SQLAlchemy 2.0 is used deliberately: the rest of the codebase (CLI,
Gradio, FastAPI sync routes) is synchronous, and FastAPI runs sync dependencies
in a threadpool. This keeps the data layer simple and consistent.

It also registers the soft-delete loader criterion (design
``docs/superpowers/specs/2026-09-22-paper-deletion-design.md`` §3):
:func:`_exclude_soft_deleted` hides every ``Attempt``, ``Upload`` and
``TeacherPaper`` row whose ``deleted_at`` is set from every ORM select issued
through *any* :class:`Session`. A statement sees deleted rows only by opting in
with ``execution_options(include_deleted=True)`` — spelled
:data:`INCLUDE_DELETED` outside this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from lemely.runtime.config import DatabaseSettings, Settings, load_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import ORMExecuteState

    from lemely.db.base import Base

#: Execution option that opts a statement out of the soft-delete filter.
#: Permitted callers, and no others: this module (the definition),
#: ``deletion_repo.py`` (delete, restore, and the recently-deleted lists,
#: student and teacher), ``purge.py``, ``attempt_repo.py`` (``_lock_live_upload``
#: must see a deleted upload to refuse it), and ``admin_repo.py`` (the
#: purge-backlog metric). Anywhere else is a bug. Callers use this constant,
#: never the bare string.
INCLUDE_DELETED = "include_deleted"

_soft_deleted: tuple[type[Base], ...] | None = None

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


def _soft_deleted_entities() -> tuple[type[Base], ...]:
    """The mapped classes that carry ``deleted_at``, resolved on first use.

    The import is deliberately function-local. Loading the models pulls in
    ``lemely.auth.mirror``, which imports :func:`session_scope` from this
    module; a top-level model import here would run that while this module is
    half-initialised and break ``import lemely.db`` (and Alembic with it).
    """
    global _soft_deleted
    if _soft_deleted is None:
        from lemely.db.models.attempts import Attempt, Upload
        from lemely.db.models.teacher_papers import TeacherPaper

        _soft_deleted = (Attempt, Upload, TeacherPaper)
    return _soft_deleted


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state: ORMExecuteState) -> None:
    """Hide soft-deleted attempts, uploads and teacher papers from every ORM select.

    Registered on the :class:`Session` **class**, not on a sessionmaker
    instance: ``sessionmaker`` is built independently here and in
    ``tests/conftest.py``, and an instance-level listener would leave the whole
    test suite unfiltered — green tests over an unprotected mechanism.

    This is the structural half of decision D3. A reader that writes a plain
    ``select(Attempt)`` is safe by default, and seeing a deleted row requires
    the deliberate act of passing ``include_deleted=True``. The alternative
    considered — a ``live_attempts()`` helper policed by a source lint — fails
    on ``session.get`` and join shapes the lint cannot see.

    Relationship lazy loads are skipped here because they inherit the criterion
    from the statement that loaded their parent (``with_loader_criteria``
    propagates to loaders) -- but only when the parent actually was loaded by
    such a statement. A parent constructed in-session (``session.add(Upload(...))``,
    then flushed or refreshed) or first loaded with ``include_deleted`` carries
    no criterion, so its relationship lazy loads return soft-deleted rows too.
    Service code that must exclude deleted children queries them explicitly
    rather than walking relationship attributes. Non-select statements
    (``text()``, ORM or Core ``update``/``delete``) are untouched -- the
    soft-delete filter never applies to UPDATE or DELETE.

    The identity map is also a gap worth knowing: once a row is loaded into a
    session, ``session.get`` returns the cached object straight from memory,
    with no SQL and thus no filter, even immediately after that row is
    soft-deleted by an ``update`` issued in the same session -- see
    ``test_warm_identity_map_hides_a_concurrent_soft_delete``.
    """
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    if state.execution_options.get(INCLUDE_DELETED):
        return
    for entity in _soft_deleted_entities():
        state.statement = state.statement.options(
            with_loader_criteria(
                entity,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )
