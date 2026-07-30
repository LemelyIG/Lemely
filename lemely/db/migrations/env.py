"""Alembic environment.

The database URL is taken from :class:`~lemely.runtime.config.Settings`
(``database.url``) rather than ``alembic.ini`` so the same precedence
(env > .env > lemely.toml > default local Supabase) applies to migrations as to
the running app. ``target_metadata`` is :attr:`lemely.db.Base.metadata` so
autogenerate sees every model imported by :mod:`lemely.db.models`.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.runtime.config import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure every model module is imported so Base.metadata is complete.
import_all_models()
target_metadata = Base.metadata

# Resolve the URL from Settings, overriding any placeholder in alembic.ini.
config.set_main_option("sqlalchemy.url", load_settings().database.url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
