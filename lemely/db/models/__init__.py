"""ORM model registry.

Every model module must be imported for :attr:`lemely.db.Base.metadata` to be
complete (Alembic autogenerate and ``create_all`` only see imported models).
:func:`import_all_models` is the single place that imports them all; Alembic's
``env.py`` and the test harness call it so no model is ever silently missed.

The relational schema (users, schools, papers, attempts, ...) is added in the
Phase-1 schema task; until then this registry is intentionally empty and the
baseline migration only establishes Alembic's version table.
"""

from __future__ import annotations


def import_all_models() -> None:
    """Import every ORM model module so ``Base.metadata`` is fully populated.

    New model modules are added here as the schema grows. Imports are performed
    lazily inside the function to avoid import-time cycles.
    """
    # Phase-1 schema modules are registered here (added with the schema task).
    return None


__all__ = ["import_all_models"]
