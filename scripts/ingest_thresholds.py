#!/usr/bin/env python
"""Ingest CAIE grade thresholds into Postgres.

Rows come from ciegt.pooruli.com (one request per syllabus, ~1,354 rows for our
three subjects across ~50 sessions back to 2011). Every row is then checked
against the official Cambridge PDF for its session, which the run has already
downloaded for the option table -- so verification costs no extra request.

Only grades the official document publishes survive. That check is not
optional politeness: ciegt reports F and G for 0606 in 216 of its 230 rows,
and Cambridge publishes neither, at component or at syllabus level. Ingesting
them would have Lemely award an F in Additional Mathematics that no Cambridge
document defines.

Sessions whose PDF is missing or unparseable are stored with ``verified=False``
and only the weaker "drop anything at or below zero raw marks" filter, so one
unreadable document does not cost us fifty readable ones.

Politeness: a descriptive User-Agent, sequential requests, and a pause between
them. This is one small site and one document host.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog

from lemely.db.models.thresholds import ComponentThreshold, OptionThreshold
from lemely.db.session import get_sessionmaker
from lemely.io.ciegt import ComponentRow, ciegt_page_url, fetch_rows, gt_pdf_url
from lemely.io.grade_boundaries import invalidate_reference_cache
from lemely.io.threshold_pdf import ParsedComponent, parse_threshold_pdf

if TYPE_CHECKING:
    from collections.abc import Callable

    from lemely.db.models.enums import SessionMonth

logger = structlog.get_logger(__name__)

DEFAULT_SUBJECTS = ("0580", "0606", "0625")
_USER_AGENT = (
    "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; educational grade-boundary ingestion)"
)
_PAUSE_SECONDS = 2.0


@dataclass
class IngestReport:
    """What one run did, for the operator and for the logs."""

    components_written: int = 0
    components_verified: int = 0
    options_written: int = 0
    grades_dropped: int = 0
    documents_unreadable: int = 0


def verify_row(
    row: ComponentRow, parsed: list[ParsedComponent] | None
) -> tuple[dict[str, int], bool]:
    """Return ``(thresholds, verified)`` for one ciegt row.

    With a document: keep only grades it publishes for this component, taking
    the document's value wherever the two differ. Without one (missing PDF, or
    a pre-2014 watermark that defeats text extraction): drop only thresholds at
    or below zero raw marks, which is not a boundary any document publishes,
    and mark the row unverified.

    The rule is deliberately "does the official document publish this grade",
    never "does this number look derived". Cambridge's own 2012 document
    states that G is set as many marks below the F threshold as the E
    threshold is above it -- Cambridge derives G by formula itself, so a
    formulaic-looking value is not evidence of fabrication. Only the
    document's own silence on a grade is.
    """
    if parsed is None:
        return {g: v for g, v in row.thresholds.items() if v > 0}, False

    official = next(
        (
            c
            for c in parsed
            if (c.paper_number, c.paper_variant) == (row.paper_number, row.paper_variant)
        ),
        None,
    )
    if official is None:
        # The document was readable but says nothing about this component.
        # Keeping the row unverified is honest; deleting it would lose coverage
        # over a parsing gap.
        return {g: v for g, v in row.thresholds.items() if v > 0}, False

    return dict(official.thresholds), True


def _fetch_pdf(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return bytes(response.read())
    except OSError as exc:
        logger.info("threshold.pdf.unavailable", url=url, error=str(exc))
        return None


def ingest(
    subject_codes: list[str],
    *,
    session_factory: Callable[[], object] | None = None,
    fetch_pdf: Callable[[str], bytes | None] = _fetch_pdf,
) -> IngestReport:
    """Fetch, verify and upsert every threshold for ``subject_codes``."""
    report = IngestReport()
    sessionmaker = session_factory or get_sessionmaker()

    for subject_code in subject_codes:
        rows = fetch_rows(subject_code)
        time.sleep(_PAUSE_SECONDS)
        by_session: dict[tuple[SessionMonth, int], list[ComponentRow]] = {}
        for row in rows:
            by_session.setdefault((row.session_month, row.session_year), []).append(row)

        for (month, year), session_rows in sorted(by_session.items(), key=lambda kv: kv[0][1]):
            url = gt_pdf_url(subject_code, month, year)
            pdf = fetch_pdf(url)
            time.sleep(_PAUSE_SECONDS)
            components, options = parse_threshold_pdf(pdf) if pdf else ([], [])
            parsed = components or None
            if parsed is None:
                report.documents_unreadable += 1

            with sessionmaker() as session, session.begin():  # type: ignore[union-attr]
                for row in session_rows:
                    thresholds, verified = verify_row(row, parsed)
                    report.grades_dropped += len(row.thresholds) - len(thresholds)
                    report.components_written += 1
                    report.components_verified += int(verified)
                    # Only a verified row may cite the Cambridge PDF as its
                    # source -- that document is what substantiated it. An
                    # unverified row's numbers were never checked against it,
                    # so it names the ciegt page they actually came from.
                    component_source_url = (
                        row.source_url if verified else ciegt_page_url(subject_code)
                    )
                    session.execute(
                        sa.dialects.postgresql.insert(ComponentThreshold)
                        .values(
                            board="caie",
                            subject_code=row.subject_code,
                            session_month=row.session_month,
                            session_year=row.session_year,
                            paper_number=row.paper_number,
                            paper_variant=row.paper_variant,
                            max_mark=row.max_mark,
                            thresholds=thresholds,
                            verified=verified,
                            source_url=component_source_url,
                        )
                        .on_conflict_do_update(
                            constraint="uq_component_thresholds_identity",
                            set_={
                                "thresholds": thresholds,
                                "verified": verified,
                                "max_mark": row.max_mark,
                                "source_url": component_source_url,
                            },
                        )
                    )
                for option in options:
                    report.options_written += 1
                    session.execute(
                        sa.dialects.postgresql.insert(OptionThreshold)
                        .values(
                            board="caie",
                            subject_code=subject_code,
                            session_month=month,
                            session_year=year,
                            option_code=option.option_code,
                            component_numbers=option.component_numbers,
                            max_mark_after_weighting=option.max_mark_after_weighting,
                            thresholds=option.thresholds,
                            source_url=url,
                        )
                        .on_conflict_do_update(
                            constraint="uq_option_thresholds_identity",
                            set_={
                                "thresholds": option.thresholds,
                                "component_numbers": option.component_numbers,
                                "max_mark_after_weighting": option.max_mark_after_weighting,
                            },
                        )
                    )

    invalidate_reference_cache()
    logger.info("threshold.ingest.done", **vars(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subjects", nargs="*", default=list(DEFAULT_SUBJECTS))
    args = parser.parse_args()
    report = ingest(args.subjects)
    print(
        f"components={report.components_written} verified={report.components_verified} "
        f"options={report.options_written} grades_dropped={report.grades_dropped} "
        f"unreadable_documents={report.documents_unreadable}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
