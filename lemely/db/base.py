"""Declarative base with a deterministic constraint-naming convention.

The naming convention is essential for Alembic: without it, Postgres assigns
implicit names to indexes/constraints that Alembic cannot reference in later
``ALTER`` migrations, which breaks the additive-migration guarantee Phases 2-5
rely on. All models in :mod:`lemely.db.models` inherit from :class:`Base`.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable names for constraints/indexes so Alembic autogenerate is reproducible
# and later migrations can target them by name.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
