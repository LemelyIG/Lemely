#!/usr/bin/env python3
"""Reset everything a local Playwright run owns: its database and its GoTrue accounts.

``web/e2e/global-setup.ts`` runs this before migrating and seeding, so every
local e2e run starts from an empty database of its own and never touches the
shared development database.

1. **Database.** Drops and recreates the database named by
   ``LEMELY_DATABASE__URL`` (``web/playwright.config.ts`` sets it). It refuses
   anything but exactly ``lemely_e2e`` on a loopback host, before it opens a
   connection, so it can never drop ``postgres`` or a remote database. The
   maintenance connection goes to the server's ``postgres`` database and only
   issues ``DROP DATABASE`` / ``CREATE DATABASE`` for the e2e name; it reads and
   writes nothing in ``postgres`` itself.
2. **Accounts.** GoTrue keeps its users in the ``auth`` schema of the shared
   ``postgres`` database, so dropping ``lemely_e2e`` cannot remove them, and every
   account of an earlier run is an orphan once the database is gone. This deletes
   the GoTrue users whose email is on the e2e domain
   (:data:`~scripts.e2e_fixtures.E2E_EMAIL_DOMAIN`), through GoTrue's admin API
   (never SQL on ``auth``), and only when ``settings.supabase.url`` is loopback.
   Accounts on any other domain are never listed for deletion.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from lemely.auth.gotrue import HttpGoTrueAdmin
from lemely.runtime.config import load_settings
from lemely.runtime.supabase_env import ensure_supabase_env
from scripts.e2e_fixtures import E2E_DATABASE_NAME, E2E_EMAIL_DOMAIN

if TYPE_CHECKING:
    from lemely.auth.gotrue import GoTrueAdmin
    from lemely.runtime.config import Settings

MAINTENANCE_DATABASE = "postgres"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_host(host: str | None) -> bool:
    """Whether ``host`` is exactly a loopback name; ``None`` is not (libpq reads ``PGHOST``)."""
    return host in LOOPBACK_HOSTS


def reset_database(url: str) -> str:
    """Drop and recreate the database named by ``url``; return its name.

    Raises:
        ValueError: the name is not exactly ``lemely_e2e``, or the host is not
            loopback. Raised before any connection is opened.
    """
    parsed = make_url(url)
    name = parsed.database
    if name != E2E_DATABASE_NAME:
        raise ValueError(
            f"Refusing to reset database {name!r}: only {E2E_DATABASE_NAME!r} may be reset."
        )
    if not is_loopback_host(parsed.host):
        raise ValueError(
            f"Refusing to reset a database on host {parsed.host!r}: the host must be one of "
            f"{sorted(LOOPBACK_HOSTS)}."
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


def is_e2e_account(email: str) -> bool:
    """Whether ``email`` is on the e2e domain exactly (case-insensitive, non-empty local part)."""
    local, separator, domain = email.strip().lower().rpartition("@")
    return bool(separator and local) and domain == E2E_EMAIL_DOMAIN


def supabase_url_is_loopback(url: str) -> bool:
    """Whether the Supabase API URL's host is exactly a loopback name."""
    return is_loopback_host(urlparse(url).hostname)


def purge_e2e_auth_users(settings: Settings, admin: GoTrueAdmin | None = None) -> int:
    """Delete every GoTrue user on the e2e domain; return how many were deleted.

    Does nothing (returns 0) unless ``settings.supabase.url`` is loopback, so a
    configuration that points at a hosted project can never have users deleted by
    a test run. ``admin`` is injectable for tests; the default is the real
    service-role-keyed :class:`~lemely.auth.gotrue.HttpGoTrueAdmin`.
    """
    if not supabase_url_is_loopback(settings.supabase.url):
        print(
            "reset_e2e_db: supabase url is not loopback; leaving GoTrue users alone",
            file=sys.stderr,
        )
        return 0
    gotrue = admin or HttpGoTrueAdmin(settings)
    doomed = [user for user in gotrue.list_users() if is_e2e_account(user.email)]
    deleted = 0
    for user in doomed:
        if gotrue.delete_user(user.id):
            deleted += 1
    return deleted


def main() -> int:
    """Reset the database configured for this run, then remove the e2e accounts."""
    ensure_supabase_env()
    settings = load_settings()
    name = reset_database(settings.database.url)
    print(f"reset_e2e_db: recreated {name}", file=sys.stderr)
    deleted = purge_e2e_auth_users(settings)
    print(f"reset_e2e_db: deleted {deleted} GoTrue users on @{E2E_EMAIL_DOMAIN}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
