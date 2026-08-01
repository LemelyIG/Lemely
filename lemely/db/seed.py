"""Idempotent database seeding: reference data and demo accounts.

Run via ``make seed`` or ``python -m lemely.db.seed`` AFTER the schema has been
migrated (``alembic upgrade head``). Seeding is split into:

* **reference data** — static, board-agnostic rows the app needs to function
  (e.g. CAIE subjects 0580/0606/0625). Safe to run on every deploy.
* **demo accounts** — the five-role demo users used by local development and the
  Phase-6 fresh-clone acceptance test.

Both are idempotent (insert-if-absent). The concrete rows are populated as the
relational schema and auth flows land in Phase 1; this module owns the seeding
entry point so callers (Makefile, tests, CI) never change.
"""

from __future__ import annotations

import structlog

from lemely.db.session import session_scope
from lemely.runtime.config import Settings, load_settings

logger = structlog.get_logger(__name__)


def seed_reference_data(settings: Settings | None = None) -> int:
    """Insert static reference rows (subjects, plan tiers, ...). Returns rows added.

    Idempotent: existing rows are left untouched. Returns 0 until the schema is
    in place (the reference models are added with the Phase-1 schema task).
    """
    settings = settings or load_settings()
    added = 0
    with session_scope(settings):
        # Reference-data inserts are added alongside their models.
        pass
    return added


def seed_demo_accounts(settings: Settings | None = None) -> int:
    """Create the five-role demo accounts. Returns accounts created.

    Idempotent: an existing account with the same email is skipped. Wired to the
    auth provider + user/profile models as they land in Phase 1.
    """
    settings = settings or load_settings()
    created = 0
    with session_scope(settings):
        # Demo-account inserts are added alongside auth + user models.
        pass
    return created


def seed_all(settings: Settings | None = None) -> None:
    """Run all idempotent seed steps in order."""
    settings = settings or load_settings()
    ref = seed_reference_data(settings)
    demo = seed_demo_accounts(settings)
    logger.info("db.seed.done", reference_rows=ref, demo_accounts=demo)


def main() -> None:
    """CLI entry point for ``python -m lemely.db.seed``."""
    from lemely.runtime.logging import configure_logging

    configure_logging()
    seed_all()


if __name__ == "__main__":
    main()
