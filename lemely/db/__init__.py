"""Database layer: SQLAlchemy 2 models, engine/session, and Alembic migrations.

The application's relational schema lives here and is owned by SQLAlchemy +
Alembic (NOT Supabase migrations). Supabase owns only the ``auth`` and
``storage`` schemas; everything in ``public`` is defined by the models in
:mod:`lemely.db.models` and migrated via ``alembic upgrade head``.
"""

from __future__ import annotations

from lemely.db.base import Base
from lemely.db.session import (
    dispose_engine,
    get_engine,
    get_sessionmaker,
    session_scope,
)

__all__ = [
    "Base",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
