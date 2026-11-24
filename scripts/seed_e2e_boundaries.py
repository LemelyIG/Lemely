#!/usr/bin/env python3
"""Seed synthetic grade boundaries into the disposable Playwright database.

``scripts/seed_e2e.py`` grades papers, and grading refuses to run on an empty
``component_thresholds`` table. A fresh ``lemely_e2e`` database has none, because
the real rows come from a network scrape (``scripts/ingest_thresholds.py``) that a
test run must not depend on. The rows are :data:`scripts.e2e_fixtures.BOUNDARY_FIXTURE_ROWS`,
the same ones ``tests/conftest.py`` installs (``example.invalid`` sources); they are
not real exam board data.

Refuses any database that is not exactly ``lemely_e2e``, and does nothing when
verified rows are already present. Run with ``PYTHONPATH`` set to the checkout, as
``web/playwright.config.ts`` does.
"""

from __future__ import annotations

import sys

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold
from lemely.db.session import get_sessionmaker
from lemely.runtime.config import load_settings
from scripts.e2e_fixtures import BOUNDARY_FIXTURE_ROWS, E2E_DATABASE_NAME


def main() -> int:
    """Insert the fixture rows into the dedicated e2e database."""
    settings = load_settings()
    name = make_url(settings.database.url).database
    if name != E2E_DATABASE_NAME:
        print(f"seed_e2e_boundaries: refusing database {name!r}", file=sys.stderr)
        return 2
    with get_sessionmaker(settings)() as session:
        existing = session.scalar(
            sa.select(sa.func.count())
            .select_from(ComponentThreshold)
            .where(ComponentThreshold.verified.is_(True))
        )
        if existing:
            return 0
        for subject, year, paper, max_mark, thresholds, source_url in BOUNDARY_FIXTURE_ROWS:
            session.add(
                ComponentThreshold(
                    subject_code=subject,
                    session_month=SessionMonth.may_june,
                    session_year=year,
                    paper_number=paper,
                    paper_variant=1,
                    max_mark=max_mark,
                    thresholds=thresholds,
                    verified=True,
                    source_url=source_url,
                )
            )
        session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
