#!/usr/bin/env python3
"""Seed synthetic grade boundaries into the disposable Playwright database.

``scripts/seed_e2e.py`` grades papers, and grading refuses to run on an empty
``component_thresholds`` table. A fresh ``lemely_e2e`` database has none, because
the real rows come from a network scrape (``scripts/ingest_thresholds.py``) that a
test run must not depend on. These rows mirror the fixture in ``tests/conftest.py``
(``example.invalid`` source URLs); they are not real exam board data.

Refuses any database whose name does not start with ``lemely_e2e``, and does
nothing when verified rows are already present.
"""

from __future__ import annotations

import sys

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold
from lemely.db.session import get_sessionmaker
from lemely.runtime.config import load_settings

# (subject_code, session_year, paper_number, max_mark, thresholds)
_FIXTURE_ROWS: tuple[tuple[str, int, int, int, dict[str, int]], ...] = (
    ("0625", 2023, 1, 40, {"C": 25, "D": 22, "E": 19, "F": 16, "G": 13}),
    ("0625", 2024, 1, 40, {"C": 26, "D": 23, "E": 20, "F": 17, "G": 14}),
    ("0625", 2019, 2, 50, {"A": 35, "B": 29, "C": 25, "D": 21, "E": 17, "F": 13, "G": 9}),
    ("0000", 2024, 1, 100, {"A": 80, "B": 70, "C": 60, "D": 50, "E": 40, "F": 30, "G": 20}),
)


def main() -> int:
    """Insert the fixture rows into the dedicated e2e database."""
    settings = load_settings()
    name = make_url(settings.database.url).database or ""
    if not name.startswith("lemely_e2e"):
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
        for subject, year, paper, max_mark, thresholds in _FIXTURE_ROWS:
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
                    source_url=f"https://example.invalid/test-fixture/{subject}_{year}_p{paper}.pdf",
                )
            )
        session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
