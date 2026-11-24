#!/usr/bin/env python3
"""Drop and recreate the disposable Playwright database (``lemely_e2e``).

``web/e2e/global-setup.ts`` runs this before migrating and seeding, so every
local e2e run starts from an empty database of its own and never touches the
shared development database. The target comes from ``LEMELY_DATABASE__URL``
(``web/playwright.config.ts`` sets it); the script refuses any database whose
name does not start with ``lemely_e2e``, so it can never drop ``postgres``.

The maintenance connection goes to the server's ``postgres`` database with the
same credentials, and only issues ``DROP DATABASE`` / ``CREATE DATABASE`` for
the e2e database; it reads and writes nothing in ``postgres`` itself.
"""

from __future__ import annotations

import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from lemely.runtime.config import load_settings

E2E_DATABASE_PREFIX = "lemely_e2e"
MAINTENANCE_DATABASE = "postgres"


def reset_database(url: str) -> str:
    """Drop and recreate the database named by ``url``; return its name.

    Raises:
        ValueError: the name does not start with ``lemely_e2e``. Raised before
            any connection is opened.
    """
    parsed = make_url(url)
    name = parsed.database or ""
    if not name.startswith(E2E_DATABASE_PREFIX):
        raise ValueError(
            f"Refusing to reset database {name!r}: its name must start with "
            f"{E2E_DATABASE_PREFIX!r}."
        )
    with psycopg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        dbname=MAINTENANCE_DATABASE,
        autocommit=True,
    ) as connection:
        identifier = sql.Identifier(name)
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(identifier))
        connection.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
    return name


def main() -> int:
    """Reset the database configured for this run."""
    name = reset_database(load_settings().database.url)
    print(f"reset_e2e_db: recreated {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
