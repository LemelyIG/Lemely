"""Tests for the exam-calendar ingestion and read paths (P5.5 chunk C, D5.8).

The whole point of this table is that **nothing invents a date**, so most of
what is pinned here is a refusal: a payload missing a field is rejected rather
than defaulted, a self-contradicting batch is rejected whole rather than
last-one-wins, and an empty calendar reports *which* of three causes produced
it rather than returning a bare empty list.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.exam_calendar_repo import (
    ExamCalendarService,
    ExamCalendarValidationError,
    TimetableEntry,
    parse_timetable_payload,
)
from lemely.db.models.academic import ExamDate, Subject
from lemely.db.models.enums import Role, SessionMonth
from lemely.db.models.profiles import StudentEnrolmentPaper, StudentSubjectEnrolment
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

_SOURCE = "CAIE June 2026 final timetable (Zone 3)"


# ---------------------------------------------------------------------------
# Fixtures.
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


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
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
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def service(pg_sessionmaker: sessionmaker[Session]) -> ExamCalendarService:
    return ExamCalendarService(pg_sessionmaker)


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> None:
    with sm.begin() as session:
        if session.scalar(select(Subject).where(Subject.code == code)) is None:
            session.add(Subject(code=code, name=f"Subject {code}"))


def _seed_student(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return uid


def _declare(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    session_month: SessionMonth | None = SessionMonth.may_june,
    session_year: int | None = 2026,
    paper_numbers: tuple[int, ...] = (2,),
) -> None:
    """Give the student a subject enrolment and the papers they intend to sit."""
    _seed_subject(sm, subject_code)
    with sm.begin() as session:
        enrolment = StudentSubjectEnrolment(
            user_id=student_id,
            subject_code=subject_code,
            session_month=session_month,
            session_year=session_year,
        )
        session.add(enrolment)
        session.flush()
        for number in paper_numbers:
            session.add(StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=number))


def _entry(
    *,
    subject_code: str = "0625",
    paper_number: int = 2,
    paper_variant: str = "22",
    exam_date: date = date(2026, 5, 12),
    session_month: SessionMonth = SessionMonth.may_june,
    session_year: int = 2026,
    starts_at_local: str | None = "09:00",
    duration_minutes: int | None = 45,
) -> TimetableEntry:
    return TimetableEntry(
        subject_code=subject_code,
        session_month=session_month,
        session_year=session_year,
        paper_number=paper_number,
        paper_variant=paper_variant,
        exam_date=exam_date,
        starts_at_local=starts_at_local,
        duration_minutes=duration_minutes,
    )


# ---------------------------------------------------------------------------
# The table ships empty (D5.8).
# ---------------------------------------------------------------------------


def test_the_table_is_empty_until_someone_ingests_a_timetable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No migration, seed or default populates a single exam date.

    Pinned as a test because the failure mode this guards against is a future
    session helpfully adding "a few obvious dates" to make the screen look
    alive. There is no CAIE timetable data on this machine; any row here that
    nobody ingested is invented.
    """
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(ExamDate)) == 0


# ---------------------------------------------------------------------------
# Ingestion.
# ---------------------------------------------------------------------------


def test_ingest_inserts_rows_and_stamps_the_source(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    _seed_subject(pg_sessionmaker)

    result = service.ingest([_entry(), _entry(paper_variant="21")], source=_SOURCE)

    assert (result.inserted, result.updated, result.unchanged) == (2, 0, 0)
    with pg_sessionmaker() as session:
        rows = session.scalars(select(ExamDate).order_by(ExamDate.paper_variant)).all()
    assert [r.paper_variant for r in rows] == ["21", "22"]
    assert {r.source for r in rows} == {_SOURCE}


def test_reingesting_a_corrected_timetable_updates_in_place(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """One paper must never appear twice with two different dates.

    A corrected timetable is republished as a matter of course, so the update
    path is the normal one, not an edge case.
    """
    _seed_subject(pg_sessionmaker)
    service.ingest([_entry()], source=_SOURCE)

    result = service.ingest([_entry(exam_date=date(2026, 5, 19))], source="CAIE corrected")

    assert (result.inserted, result.updated, result.unchanged) == (0, 1, 0)
    with pg_sessionmaker() as session:
        (row,) = session.scalars(select(ExamDate)).all()
    assert row.exam_date == date(2026, 5, 19)
    assert row.source == "CAIE corrected"


def test_reingesting_an_identical_timetable_changes_nothing(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    _seed_subject(pg_sessionmaker)
    service.ingest([_entry()], source=_SOURCE)

    result = service.ingest([_entry()], source=_SOURCE)

    assert (result.inserted, result.updated, result.unchanged) == (0, 0, 1)


def test_ingest_without_a_source_is_refused(service: ExamCalendarService) -> None:
    """A row that cannot name its document is indistinguishable from invented."""
    with pytest.raises(ExamCalendarValidationError, match="source"):
        service.ingest([_entry()], source="   ")


def test_a_batch_that_contradicts_itself_is_rejected_whole(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """Last-one-wins would let a stale line overwrite a correct one silently."""
    _seed_subject(pg_sessionmaker)

    with pytest.raises(ExamCalendarValidationError, match="disagrees with itself"):
        service.ingest(
            [_entry(), _entry(exam_date=date(2026, 6, 1))],
            source=_SOURCE,
        )

    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(ExamDate)) == 0


def test_a_non_positive_paper_number_is_refused_with_the_offending_paper_named(
    service: ExamCalendarService,
) -> None:
    with pytest.raises(ExamCalendarValidationError, match="0625/22"):
        service.ingest([_entry(paper_number=0)], source=_SOURCE)


def test_the_unique_constraint_is_real_not_just_a_service_convention(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Inserted through the session, bypassing the service entirely."""
    _seed_subject(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        for _ in range(2):
            session.add(
                ExamDate(
                    subject_code="0625",
                    session_month=SessionMonth.may_june,
                    session_year=2026,
                    paper_number=2,
                    paper_variant="22",
                    exam_date=date(2026, 5, 12),
                    source=_SOURCE,
                )
            )
        with pytest.raises(IntegrityError):
            session.flush()


# ---------------------------------------------------------------------------
# Payload parsing — nothing is defaulted.
# ---------------------------------------------------------------------------


def _payload_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "subjectCode": "0625",
        "sessionMonth": "may_june",
        "sessionYear": 2026,
        "paperNumber": 2,
        "paperVariant": "22",
        "examDate": "2026-05-12",
        "startsAtLocal": "09:00",
        "durationMinutes": 45,
    }
    item.update(overrides)
    return item


def test_a_well_formed_payload_parses(pg_sessionmaker: sessionmaker[Session]) -> None:
    (entry,) = parse_timetable_payload([_payload_item()])

    assert entry.subject_code == "0625"
    assert entry.session_month is SessionMonth.may_june
    assert entry.exam_date == date(2026, 5, 12)
    assert entry.duration_minutes == 45


@pytest.mark.parametrize(
    "missing",
    ["subjectCode", "sessionMonth", "sessionYear", "paperNumber", "paperVariant", "examDate"],
)
def test_a_missing_required_field_is_refused_never_defaulted(missing: str) -> None:
    """The convenient default is the bug.

    Inferring ``paperNumber`` from the variant or ``sessionYear`` from the
    current year would each manufacture a fact about a real exam.
    """
    item = _payload_item()
    del item[missing]

    with pytest.raises(ExamCalendarValidationError, match=missing):
        parse_timetable_payload([item])


def test_the_optional_fields_really_are_optional(pg_sessionmaker: sessionmaker[Session]) -> None:
    item = _payload_item()
    del item["startsAtLocal"]
    del item["durationMinutes"]

    (entry,) = parse_timetable_payload([item])

    assert entry.starts_at_local is None
    assert entry.duration_minutes is None


def test_an_unparseable_date_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(ExamCalendarValidationError, match="ISO date"):
        parse_timetable_payload([_payload_item(examDate="12 May 2026")])


def test_an_unknown_session_month_is_refused_and_lists_the_known_ones(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(ExamCalendarValidationError, match="may_june"):
        parse_timetable_payload([_payload_item(sessionMonth="summer")])


def test_a_boolean_is_not_accepted_as_an_integer(pg_sessionmaker: sessionmaker[Session]) -> None:
    """``bool`` is an ``int`` subclass; ``True`` would otherwise become paper 1."""
    with pytest.raises(ExamCalendarValidationError, match="paperNumber"):
        parse_timetable_payload([_payload_item(paperNumber=True)])


def test_one_bad_entry_rejects_the_whole_document(pg_sessionmaker: sessionmaker[Session]) -> None:
    """No partial ingest: half a timetable looks like a complete one."""
    with pytest.raises(ExamCalendarValidationError, match="Entry 1"):
        parse_timetable_payload([_payload_item(), _payload_item(examDate="nonsense")])


def test_a_payload_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(ExamCalendarValidationError, match="list of entries"):
        parse_timetable_payload({"entries": []})


# ---------------------------------------------------------------------------
# The student read — three empty causes, kept apart.
# ---------------------------------------------------------------------------


def test_a_student_who_has_not_onboarded_gets_no_enrolment_not_no_timetable(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """Blaming Cambridge for a blank the student can fill in is the failure."""
    student = _seed_student(pg_sessionmaker)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "no_enrolment"
    assert calendar.entries == []


def test_an_onboarded_student_with_no_ingested_timetable_gets_no_timetable(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """The state this build actually ships in (D5.8).

    The paper still appears — the student is told we know what they are
    sitting and do not yet hold its date, which is the truth.
    """
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "no_timetable"
    (entry,) = calendar.entries
    assert entry.paper_number == 2
    assert entry.availability == "no_timetable"
    assert entry.dates == []


def test_a_paper_whose_enrolment_names_no_session_is_no_session(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student, session_month=None, session_year=None)

    (entry,) = service.calendar_for_student(student).entries

    assert entry.availability == "no_session"
    assert entry.dates == []


def test_a_declared_paper_with_an_ingested_date_is_dated(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    service.ingest([_entry()], source=_SOURCE)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "available"
    (entry,) = calendar.entries
    assert entry.availability == "dated"
    (dated,) = entry.dates
    assert dated.exam_date == date(2026, 5, 12)
    assert dated.paper_variant == "22"
    assert dated.source == _SOURCE


def test_every_variant_of_a_declared_paper_number_is_returned(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """The student declared a paper *number*; the timetable dates *variants*.

    Silently picking the earliest would invent the one fact the student never
    gave us — which variant they sit.
    """
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    service.ingest(
        [
            _entry(paper_variant="22", exam_date=date(2026, 5, 12)),
            _entry(paper_variant="21", exam_date=date(2026, 5, 14)),
        ],
        source=_SOURCE,
    )

    (entry,) = service.calendar_for_student(student).entries

    assert [d.paper_variant for d in entry.dates] == ["22", "21"]
    assert [d.exam_date for d in entry.dates] == [date(2026, 5, 12), date(2026, 5, 14)]


def test_dates_from_another_session_do_not_leak_into_this_ones_calendar(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student, session_month=SessionMonth.may_june, session_year=2026)
    service.ingest([_entry(session_month=SessionMonth.oct_nov, session_year=2025)], source=_SOURCE)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "no_timetable"
    assert calendar.entries[0].dates == []


def test_a_past_date_in_the_declared_session_is_still_reported(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    """Not filtered by "now", deliberately.

    Dropping past dates would make a student's calendar empty out halfway
    through their own exam series, so ``no_timetable`` — the state meaning "we
    have no data" — would fire when we have all of it.
    """
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    service.ingest([_entry(exam_date=date(2020, 5, 12))], source=_SOURCE)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "available"
    assert calendar.entries[0].dates[0].exam_date == date(2020, 5, 12)


def test_one_students_declared_papers_are_not_visible_on_anothers_calendar(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    declared = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, declared)
    other = _seed_student(pg_sessionmaker)

    assert service.calendar_for_student(other).availability == "no_enrolment"


def test_several_declared_papers_each_get_their_own_entry(
    pg_sessionmaker: sessionmaker[Session], service: ExamCalendarService
) -> None:
    student = _seed_student(pg_sessionmaker)
    _declare(pg_sessionmaker, student, paper_numbers=(2, 4))
    service.ingest([_entry(paper_number=2, paper_variant="22")], source=_SOURCE)

    calendar = service.calendar_for_student(student)

    assert calendar.availability == "available"
    assert [(e.paper_number, e.availability) for e in calendar.entries] == [
        (2, "dated"),
        (4, "no_timetable"),
    ]
