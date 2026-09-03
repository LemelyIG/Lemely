"""The verification rule that keeps fabricated grades out of the database.

The premise this whole design rests on was measured, not assumed: 57 ciegt
component records were compared against the official PDFs and 51 matched
exactly. The 6 that did not were all 0606, where ciegt carries F and G grades
Cambridge does not publish -- and 0606's option table publishes A*-E too, so it
is not a tier artefact. These tests pin the rule that removes them.

The second half of this module proves ``ingest`` itself is idempotent against a
real Postgres database, closing a gap an earlier review flagged: nothing else
in the suite exercised ``option_thresholds``' ``uq_option_thresholds_identity``
constraint or its NOT NULL ``source_url``, even though ``ingest`` performs an
``on_conflict_do_update`` against exactly that constraint.

Nothing here touches the network. ``fetch_rows`` and PDF fetching are always
faked; ``verify_row`` is pure and needs neither network nor database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold, OptionThreshold
from lemely.io.ciegt import ComponentRow, ciegt_page_url, gt_pdf_url
from lemely.io.threshold_pdf import ParsedComponent, ParsedOption
from lemely.runtime.config import DatabaseSettings
from scripts.ingest_thresholds import ingest, verify_row

if TYPE_CHECKING:
    from collections.abc import Callable

import_all_models()


def _row(thresholds: dict[str, int]) -> ComponentRow:
    return ComponentRow(
        subject_code="0606",
        session_month=SessionMonth.may_june,
        session_year=2024,
        paper_number=1,
        paper_variant=1,
        max_mark=80,
        thresholds=thresholds,
        source_url="https://example.invalid/0606_s24_gt.pdf",
    )


def test_a_grade_the_document_does_not_publish_is_dropped() -> None:
    """0606 M/J 24 component 11, verbatim from both sources. ciegt reports
    A-G; the official PDF publishes A-E. F and G must not survive."""
    row = _row({"A": 53, "B": 38, "C": 22, "D": 16, "E": 10, "F": 4, "G": 0})
    parsed = [
        ParsedComponent(
            paper_number=1,
            paper_variant=1,
            max_mark=80,
            thresholds={"A": 53, "B": 38, "C": 22, "D": 16, "E": 10},
        )
    ]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert thresholds == {"A": 53, "B": 38, "C": 22, "D": 16, "E": 10}
    assert verified is True
    assert max_mark == 80


def test_the_document_wins_when_a_value_differs() -> None:
    row = _row({"A": 53, "B": 99})
    parsed = [
        ParsedComponent(paper_number=1, paper_variant=1, max_mark=80, thresholds={"A": 53, "B": 38})
    ]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert thresholds["B"] == 38
    assert verified is True
    assert max_mark == 80


def test_the_documents_max_mark_wins_when_it_differs_from_ciegts() -> None:
    """Finding C2: every percentage divides by ``max_mark``, so a "verified"
    row citing Cambridge for its thresholds but keeping ciegt's own
    (unconfirmed) ``max_mark`` would misattribute the one number scaling the
    whole grade ladder. ``row.max_mark`` (from ``_row``) is 80; the document
    disagrees and must win."""
    row = _row({"A": 53})
    parsed = [ParsedComponent(paper_number=1, paper_variant=1, max_mark=75, thresholds={"A": 53})]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert verified is True
    assert max_mark == 75
    assert thresholds == {"A": 53}


def test_without_a_document_only_impossible_values_are_dropped() -> None:
    """The fallback for a session whose PDF is missing or watermark-mangled.
    A threshold of zero raw marks is not a published boundary; a threshold of
    four is not obviously wrong, so it survives -- which is exactly why the
    row is marked unverified rather than trusted. The unverified row keeps
    ciegt's own max_mark since the document was never read for it."""
    row = _row({"A": 53, "E": 10, "F": 4, "G": 0})
    thresholds, verified, max_mark = verify_row(row, None)
    assert thresholds == {"A": 53, "E": 10, "F": 4}
    assert verified is False
    assert max_mark == row.max_mark


def test_a_component_missing_from_the_document_is_unverified_not_deleted() -> None:
    row = _row({"A": 53})
    parsed = [ParsedComponent(paper_number=9, paper_variant=9, max_mark=80, thresholds={"A": 1})]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert thresholds == {"A": 53}
    assert verified is False
    assert max_mark == row.max_mark


def test_a_formulaic_looking_threshold_is_kept_when_the_document_publishes_it() -> None:
    """CAIE's own 2012 document says "G is set as many marks below the F
    threshold as the E threshold is above it" - Cambridge derives G by formula
    itself. The rule is "does the document publish this grade", never "does
    this number look derived"."""
    row = _row({"E": 21, "F": 15, "G": 9})
    parsed = [
        ParsedComponent(
            paper_number=1, paper_variant=1, max_mark=80, thresholds={"E": 21, "F": 15, "G": 9}
        )
    ]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert thresholds == {"E": 21, "F": 15, "G": 9}
    assert verified is True
    assert max_mark == 80


def test_an_empty_official_parse_is_unverified_not_stored_verified() -> None:
    """Finding C3: a component that matches by (paper_number, paper_variant)
    but whose thresholds parsed empty (every grade cell unreadable) must not
    be stored ``verified=True`` -- that would have Cambridge cited for a row
    that decides nothing, and downstream a 95% candidate would resolve
    against an empty boundary map."""
    row = _row({"A": 53, "B": 38})
    parsed = [ParsedComponent(paper_number=1, paper_variant=1, max_mark=80, thresholds={})]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert verified is False
    assert max_mark == row.max_mark
    # Falls back to the weak ">0 raw marks" filter over ciegt's own values.
    assert thresholds == {"A": 53, "B": 38}


def test_a_component_with_an_unrecognised_cell_is_unverified() -> None:
    """A component the document names and even parses *some* real values
    for, but with one glyph the parser could not classify as either a value
    or a not-applicable marker, must stay unverified -- a partial, garbled
    read is worse than no read, because it is invisible in the thresholds
    dict alone."""
    row = _row({"A": 53, "B": 38, "C": 22})
    parsed = [
        ParsedComponent(
            paper_number=1,
            paper_variant=1,
            max_mark=80,
            thresholds={"B": 38, "C": 22},
            has_unrecognised_cell=True,
        )
    ]
    thresholds, verified, max_mark = verify_row(row, parsed)
    assert verified is False
    assert max_mark == row.max_mark
    assert thresholds == {"A": 53, "B": 38, "C": 22}


# ---------------------------------------------------------------------------
# Integration layer -- real Postgres, skipped when unreachable. No network:
# fetch_rows and fetch_pdf are monkeypatched, never called for real.
# ---------------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[sa.Engine]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ingest paces itself with real network hosts in mind; tests hit neither."""
    monkeypatch.setattr("scripts.ingest_thresholds.time.sleep", lambda _seconds: None)


def _one_row_one_option(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Callable[[str], list[ComponentRow]], Callable[[str], bytes | None]]:
    row = _row({"A": 53, "B": 38})

    def fake_fetch_rows(subject_code: str) -> list[ComponentRow]:
        assert subject_code == "0606"
        return [row]

    parsed_components = [
        ParsedComponent(paper_number=1, paper_variant=1, max_mark=80, thresholds={"A": 53, "B": 38})
    ]
    parsed_options = [
        ParsedOption(
            option_code="AX",
            component_numbers=[11],
            max_mark_after_weighting=80,
            thresholds={"A*": 60, "A": 53, "B": 38},
        )
    ]

    def fake_fetch_pdf(url: str) -> bytes | None:
        return b"placeholder"

    monkeypatch.setattr("scripts.ingest_thresholds.fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(
        "scripts.ingest_thresholds.parse_threshold_pdf",
        lambda pdf_bytes: (parsed_components, parsed_options),
    )
    return fake_fetch_rows, fake_fetch_pdf


def test_ingest_upserts_component_and_option_thresholds(
    pg_engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, fake_fetch_pdf = _one_row_one_option(monkeypatch)
    factory = sessionmaker(bind=pg_engine, future=True)

    report = ingest(["0606"], session_factory=factory, fetch_pdf=fake_fetch_pdf)

    assert report.components_written == 1
    assert report.components_verified == 1
    assert report.options_written == 1

    with Session(pg_engine) as session:
        component = session.query(ComponentThreshold).one()
        assert component.verified is True
        assert component.thresholds == {"A": 53, "B": 38}

        option = session.query(OptionThreshold).one()
        assert option.thresholds == {"A*": 60, "A": 53, "B": 38}
        assert option.source_url


def test_a_second_ingest_of_the_same_option_updates_rather_than_duplicates(
    pg_engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ingest`` performs ``on_conflict_do_update`` against
    ``uq_option_thresholds_identity``. A second run of the same session must
    change the one existing row, not raise a unique-violation and not leave a
    second row beside it -- that is what makes the ingest idempotent."""
    _, fake_fetch_pdf = _one_row_one_option(monkeypatch)
    factory = sessionmaker(bind=pg_engine, future=True)

    ingest(["0606"], session_factory=factory, fetch_pdf=fake_fetch_pdf)

    # Change the option's own thresholds before the second run, so a genuine
    # UPDATE is distinguishable from a no-op re-insert.
    updated_options = [
        ParsedOption(
            option_code="AX",
            component_numbers=[11],
            max_mark_after_weighting=80,
            thresholds={"A*": 61, "A": 54, "B": 39},
        )
    ]
    parsed_components = [
        ParsedComponent(paper_number=1, paper_variant=1, max_mark=80, thresholds={"A": 53, "B": 38})
    ]
    monkeypatch.setattr(
        "scripts.ingest_thresholds.parse_threshold_pdf",
        lambda pdf_bytes: (parsed_components, updated_options),
    )

    ingest(["0606"], session_factory=factory, fetch_pdf=fake_fetch_pdf)

    with Session(pg_engine) as session:
        options = session.query(OptionThreshold).all()
        assert len(options) == 1
        assert options[0].thresholds == {"A*": 61, "A": 54, "B": 39}

        components = session.query(ComponentThreshold).all()
        assert len(components) == 1


def test_source_url_names_the_document_actually_read(
    pg_engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verified row's ``source_url`` is the Cambridge PDF that confirmed it.

    An unverified row must not carry that same URL: the document was never
    read for it, so citing it would misattribute the number to Cambridge --
    exactly the failure mode this whole design exists to prevent. Its
    ``source_url`` instead names the ciegt page the number actually came
    from.
    """
    subject_code = "0625"
    month, year = SessionMonth.oct_nov, 2023
    verified_row = ComponentRow(
        subject_code=subject_code,
        session_month=month,
        session_year=year,
        paper_number=3,
        paper_variant=3,
        max_mark=80,
        thresholds={"A": 60},
        source_url=gt_pdf_url(subject_code, month, year),
    )
    unverified_row = ComponentRow(
        subject_code=subject_code,
        session_month=month,
        session_year=year,
        paper_number=4,
        paper_variant=4,
        max_mark=80,
        thresholds={"A": 60},
        source_url=gt_pdf_url(subject_code, month, year),
    )

    def fake_fetch_rows(code: str) -> list[ComponentRow]:
        assert code == subject_code
        return [verified_row, unverified_row]

    # The document is readable and confirms component 33 -- but says nothing
    # about component 44, so that row stays unverified even though a PDF was
    # fetched for the session.
    parsed_components = [
        ParsedComponent(paper_number=3, paper_variant=3, max_mark=80, thresholds={"A": 60})
    ]
    monkeypatch.setattr("scripts.ingest_thresholds.fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(
        "scripts.ingest_thresholds.parse_threshold_pdf",
        lambda pdf_bytes: (parsed_components, []),
    )
    factory = sessionmaker(bind=pg_engine, future=True)

    ingest([subject_code], session_factory=factory, fetch_pdf=lambda url: b"placeholder")

    with Session(pg_engine) as session:
        verified = (
            session.query(ComponentThreshold)
            .filter_by(subject_code=subject_code, paper_number=3, paper_variant=3)
            .one()
        )
        unverified = (
            session.query(ComponentThreshold)
            .filter_by(subject_code=subject_code, paper_number=4, paper_variant=4)
            .one()
        )

        assert verified.verified is True
        assert verified.source_url == gt_pdf_url(subject_code, month, year)
        assert "papacambridge" in verified.source_url

        assert unverified.verified is False
        assert unverified.source_url == ciegt_page_url(subject_code)
        assert "papacambridge" not in unverified.source_url
        assert "pastpapers" not in unverified.source_url


def test_a_non_positive_max_mark_is_rejected_by_the_database(pg_engine: sa.Engine) -> None:
    """Finding C3: ``ck_component_thresholds_max_mark_positive`` is the
    backstop against a non-positive ``max_mark`` ever being stored, regardless
    of which code path writes the row -- ``_percentages`` divides by it for
    every graded paper."""
    with pytest.raises(sa.exc.IntegrityError), Session(pg_engine) as session, session.begin():
        session.add(
            ComponentThreshold(
                board="caie",
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=1,
                paper_variant=1,
                max_mark=0,
                thresholds={"A": 1},
                verified=True,
                source_url="https://example.invalid/gt.pdf",
            )
        )
