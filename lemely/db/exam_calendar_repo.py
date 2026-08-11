"""Exam-calendar ingestion and the student's dated-papers read (P5.5 chunk C, D5.8).

**This service reads a table that is empty in every environment this build
ships, and that is deliberate.** There is no CAIE timetable data anywhere on
this machine: ``Sources/`` holds mark schemes only, and the PaperScraper
corpus fetches question papers and grade-boundary documents and has never
fetched a timetable. Real dates live in a separate official CAIE timetable
document nothing here has a path to.

So the shape of this module is: a strict ingestion path that accepts a
published timetable and refuses anything it cannot verify, plus a read path
that says *why* it has nothing rather than returning a bare empty list. What
is **not** here is any code that produces a date from something other than an
ingested row — no derivation from session codes, no "papers are usually in
May", no seeded sample data. A wrong exam date is materially worse than a
missing one: this surface exists to be a countdown a student plans revision
around, so a fabricated date misinforms rather than merely disappoints (UI
spec 1.4, "never invent precision").

The tri-state availability the read path returns is the P4.5/D4.10 pattern —
the same reason the practice generator refuses honestly for 0580 and 0606
instead of generating something. Three causes are kept apart because they ask
the student for three different things:

* ``no_enrolment`` — they have not told us what they are sitting. Finish
  onboarding.
* ``no_timetable`` — they have, and we hold no official dates for it. Nothing
  they can do; the platform owes them the data.
* ``available`` — at least one paper is dated.

Collapsing the first two into one empty state would tell a student who never
onboarded that Cambridge has not published dates yet, which is a lie about a
third party.

**Past papers in the declared session are not filtered out.** A session's
components sit within a few weeks of each other, so dropping past dates would
make a student's calendar go empty halfway through their own exam series and
read as ``no_timetable`` — the state that means "we have no data" would start
firing when we have all of it. The consuming screen decides what a past date
looks like; the service reports what the timetable says.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from lemely.db.models.academic import ExamDate
from lemely.db.models.enums import SessionMonth
from lemely.db.models.profiles import StudentEnrolmentPaper, StudentSubjectEnrolment

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.orm import Session, sessionmaker

#: Availability of a student's calendar as a whole.
CalendarAvailability = Literal["available", "no_enrolment", "no_timetable"]

#: Availability of one declared paper within that calendar.
PaperAvailability = Literal["dated", "no_timetable", "no_session"]


class ExamCalendarError(Exception):
    """Base class for exam-calendar failures."""


class ExamCalendarValidationError(ExamCalendarError):
    """A timetable payload is malformed, or an entry is unusable (→ 422)."""


@dataclass(frozen=True, slots=True)
class TimetableEntry:
    """One row of an official timetable, before it reaches the database."""

    subject_code: str
    session_month: SessionMonth
    session_year: int
    paper_number: int
    paper_variant: str
    exam_date: date
    starts_at_local: str | None = None
    duration_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one :meth:`ExamCalendarService.ingest` call changed."""

    inserted: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class ExamDateRow:
    """One dated variant, detached from its ORM session."""

    paper_variant: str
    exam_date: date
    starts_at_local: str | None
    duration_minutes: int | None
    source: str


@dataclass(frozen=True, slots=True)
class StudentExamEntry:
    """One paper the student declared, with whatever dates we honestly hold.

    ``dates`` is a **list** because the timetable's grain is the variant and
    the student declares only a paper number: a student who said "Paper 2"
    may map to ``0625/21``, ``/22`` and ``/23``, which can sit on different
    days. Returning all of them and letting the surface say "your Paper 2 is
    one of these" is the honest answer; silently picking the earliest would
    invent the one fact the student did not give us.
    """

    subject_code: str
    session_month: SessionMonth | None
    session_year: int | None
    paper_number: int
    availability: PaperAvailability
    dates: list[ExamDateRow]


@dataclass(frozen=True, slots=True)
class StudentExamCalendar:
    """The student's whole calendar, with the reason when it is empty."""

    availability: CalendarAvailability
    entries: list[StudentExamEntry]


class ExamCalendarService:
    """Ingest official timetables; read one student's dated papers."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to its session factory.

        **No clock is injected**, unlike its Phase-5 siblings. Nothing here
        compares a date to "now": ingestion is time-independent, and the read
        path deliberately does not filter past dates (see the module
        docstring). A clock would be an unused parameter implying a
        time-dependence this service does not have.
        """
        self._sessionmaker = sessionmaker

    # -- Ingestion --------------------------------------------------------------

    def ingest(self, entries: Iterable[TimetableEntry], *, source: str) -> IngestResult:
        """Upsert timetable rows, keyed on ``uq_exam_dates_variant``.

        ``source`` names the published document every one of these rows came
        from and is stored on each. It is required and must be non-empty:
        a row that cannot name its document is indistinguishable from an
        invented one, which is the single thing this table exists to prevent
        (D5.8).

        Idempotent by the database's unique key rather than by care, so
        re-ingesting a corrected timetable **updates dates in place**. The
        alternative — appending — would make one paper appear twice on a
        student's calendar with two different dates, which is worse than
        having no calendar at all.

        Raises:
            ExamCalendarValidationError: ``source`` is blank, an entry is
                internally inconsistent, or two entries in the same batch
                claim the same variant with different dates (the document
                itself disagrees; guessing which line is right is not this
                code's call).
        """
        if not source.strip():
            raise ExamCalendarValidationError("Every ingested exam date must name its source")
        materialised = [_validated(entry) for entry in entries]
        _reject_internal_conflicts(materialised)

        inserted = updated = unchanged = 0
        with self._sessionmaker() as session, session.begin():
            for entry in materialised:
                existing = session.scalar(
                    select(ExamDate).where(
                        ExamDate.subject_code == entry.subject_code,
                        ExamDate.session_month == entry.session_month,
                        ExamDate.session_year == entry.session_year,
                        ExamDate.paper_variant == entry.paper_variant,
                    )
                )
                if existing is None:
                    session.add(
                        ExamDate(
                            subject_code=entry.subject_code,
                            session_month=entry.session_month,
                            session_year=entry.session_year,
                            paper_number=entry.paper_number,
                            paper_variant=entry.paper_variant,
                            exam_date=entry.exam_date,
                            starts_at_local=entry.starts_at_local,
                            duration_minutes=entry.duration_minutes,
                            source=source,
                        )
                    )
                    inserted += 1
                    continue

                changed = (
                    existing.exam_date,
                    existing.paper_number,
                    existing.starts_at_local,
                    existing.duration_minutes,
                    existing.source,
                ) != (
                    entry.exam_date,
                    entry.paper_number,
                    entry.starts_at_local,
                    entry.duration_minutes,
                    source,
                )
                if not changed:
                    unchanged += 1
                    continue
                existing.exam_date = entry.exam_date
                existing.paper_number = entry.paper_number
                existing.starts_at_local = entry.starts_at_local
                existing.duration_minutes = entry.duration_minutes
                existing.source = source
                updated += 1

        return IngestResult(inserted=inserted, updated=updated, unchanged=unchanged)

    # -- Read -------------------------------------------------------------------

    def calendar_for_student(self, student_id: uuid.UUID | str) -> StudentExamCalendar:
        """Return every paper this student declared, with its dates if we hold any.

        A paper whose enrolment has no session (both ``session_month`` and
        ``session_year`` are nullable on ``student_subject_enrolments``) comes
        back as ``no_session`` rather than being dropped or matched against
        some other session's dates. It is a real gap in *their* onboarding,
        and it must not be presented as the platform lacking data.
        """
        student_uuid = _as_uuid(student_id)

        with self._sessionmaker() as session:
            declared = session.execute(
                select(
                    StudentSubjectEnrolment.subject_code,
                    StudentSubjectEnrolment.session_month,
                    StudentSubjectEnrolment.session_year,
                    StudentEnrolmentPaper.paper_number,
                )
                .join(
                    StudentEnrolmentPaper,
                    StudentEnrolmentPaper.enrolment_id == StudentSubjectEnrolment.id,
                )
                .where(StudentSubjectEnrolment.user_id == student_uuid)
                .order_by(
                    StudentSubjectEnrolment.subject_code,
                    StudentEnrolmentPaper.paper_number,
                )
            ).all()

            if not declared:
                return StudentExamCalendar(availability="no_enrolment", entries=[])

            entries = [
                self._entry_for(session, subject_code, month, year, paper_number)
                for subject_code, month, year, paper_number in declared
            ]

        availability: CalendarAvailability = (
            "available" if any(entry.dates for entry in entries) else "no_timetable"
        )
        return StudentExamCalendar(availability=availability, entries=entries)

    def _entry_for(
        self,
        session: Session,
        subject_code: str,
        session_month: SessionMonth | None,
        session_year: int | None,
        paper_number: int,
    ) -> StudentExamEntry:
        if session_month is None or session_year is None:
            return StudentExamEntry(
                subject_code=subject_code,
                session_month=session_month,
                session_year=session_year,
                paper_number=paper_number,
                availability="no_session",
                dates=[],
            )

        rows = session.scalars(
            select(ExamDate)
            .where(
                ExamDate.subject_code == subject_code,
                ExamDate.session_month == session_month,
                ExamDate.session_year == session_year,
                ExamDate.paper_number == paper_number,
            )
            .order_by(ExamDate.exam_date, ExamDate.paper_variant)
        ).all()

        dates = [
            ExamDateRow(
                paper_variant=row.paper_variant,
                exam_date=row.exam_date,
                starts_at_local=row.starts_at_local,
                duration_minutes=row.duration_minutes,
                source=row.source,
            )
            for row in rows
        ]
        return StudentExamEntry(
            subject_code=subject_code,
            session_month=session_month,
            session_year=session_year,
            paper_number=paper_number,
            availability="dated" if dates else "no_timetable",
            dates=dates,
        )


# ---------------------------------------------------------------------------
# Payload parsing — the documented ingestion format.
# ---------------------------------------------------------------------------


def parse_timetable_payload(payload: object) -> list[TimetableEntry]:
    """Turn a decoded JSON timetable document into validated entries.

    The expected shape is a list of objects, each with ``subjectCode``,
    ``sessionMonth`` (a :class:`~lemely.db.models.enums.SessionMonth` value),
    ``sessionYear``, ``paperNumber``, ``paperVariant`` and ``examDate``
    (ISO ``YYYY-MM-DD``), plus optional ``startsAtLocal`` and
    ``durationMinutes``.

    **Every field is required to be present and well-formed; nothing is
    defaulted.** A missing ``paperNumber`` is not inferred from the variant,
    a missing ``sessionYear`` is not taken from the current year, and a
    partially-parsed document is rejected whole rather than ingested with the
    good rows. Each of those conveniences would silently manufacture a fact
    about a real exam, and this is precisely the module where that must not
    happen (D5.8).

    Raises:
        ExamCalendarValidationError: The payload is not a list of objects, or
            any entry is missing a field, has a wrong type, or carries an
            unparseable date or session month. The message names the index so
            a human can fix the source document.
    """
    if not isinstance(payload, list):
        raise ExamCalendarValidationError("A timetable document must be a list of entries")
    return [_entry_from_mapping(index, item) for index, item in enumerate(payload)]


def _entry_from_mapping(index: int, item: object) -> TimetableEntry:
    if not isinstance(item, dict):
        raise ExamCalendarValidationError(f"Entry {index} is not an object")

    def required(key: str) -> object:
        if key not in item or item[key] is None:
            raise ExamCalendarValidationError(f"Entry {index} is missing {key!r}")
        return item[key]

    subject_code = _as_str(index, "subjectCode", required("subjectCode"))
    paper_variant = _as_str(index, "paperVariant", required("paperVariant"))
    session_month = _as_session_month(index, required("sessionMonth"))
    session_year = _as_int(index, "sessionYear", required("sessionYear"))
    paper_number = _as_int(index, "paperNumber", required("paperNumber"))
    exam_date = _as_date(index, required("examDate"))

    starts_at_local = item.get("startsAtLocal")
    if starts_at_local is not None:
        starts_at_local = _as_str(index, "startsAtLocal", starts_at_local)
    duration_minutes = item.get("durationMinutes")
    if duration_minutes is not None:
        duration_minutes = _as_int(index, "durationMinutes", duration_minutes)

    return _validated(
        TimetableEntry(
            subject_code=subject_code,
            session_month=session_month,
            session_year=session_year,
            paper_number=paper_number,
            paper_variant=paper_variant,
            exam_date=exam_date,
            starts_at_local=starts_at_local,
            duration_minutes=duration_minutes,
        )
    )


def _as_str(index: int, key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExamCalendarValidationError(f"Entry {index}: {key!r} must be a non-empty string")
    return value.strip()


def _as_int(index: int, key: str, value: object) -> int:
    # bool is an int subclass; True would otherwise sail through as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExamCalendarValidationError(f"Entry {index}: {key!r} must be an integer")
    return value


def _as_date(index: int, value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ExamCalendarValidationError(f"Entry {index}: 'examDate' must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExamCalendarValidationError(
            f"Entry {index}: 'examDate' is not an ISO date: {value!r}"
        ) from exc


def _as_session_month(index: int, value: object) -> SessionMonth:
    if isinstance(value, SessionMonth):
        return value
    if not isinstance(value, str):
        raise ExamCalendarValidationError(f"Entry {index}: 'sessionMonth' must be a string")
    try:
        return SessionMonth(value)
    except ValueError as exc:
        known = ", ".join(member.value for member in SessionMonth)
        raise ExamCalendarValidationError(
            f"Entry {index}: unknown sessionMonth {value!r} (expected one of {known})"
        ) from exc


def _validated(entry: TimetableEntry) -> TimetableEntry:
    """Reject an entry the database's CHECK constraints would reject anyway.

    Duplicated deliberately rather than left to the constraints: a
    ``IntegrityError`` surfacing from the middle of a batch names a constraint,
    not the offending line of the source document, and whoever is ingesting a
    timetable needs to know which row to fix.
    """
    if entry.paper_number <= 0:
        raise ExamCalendarValidationError(
            f"{entry.subject_code}/{entry.paper_variant}: paper number must be positive"
        )
    if not entry.paper_variant.strip():
        raise ExamCalendarValidationError(f"{entry.subject_code}: paper variant must not be blank")
    if entry.duration_minutes is not None and entry.duration_minutes <= 0:
        raise ExamCalendarValidationError(
            f"{entry.subject_code}/{entry.paper_variant}: duration must be positive"
        )
    return entry


def _reject_internal_conflicts(entries: Sequence[TimetableEntry]) -> None:
    """Refuse a batch that contradicts itself on the unique key.

    Two lines claiming the same variant with different dates means the source
    document disagrees with itself (or was assembled from two documents).
    Taking the last one silently would let a stale line overwrite a correct
    one with no trace, so the whole batch is rejected and a human reconciles
    it against the published timetable.
    """
    seen: dict[tuple[str, SessionMonth, int, str], TimetableEntry] = {}
    for entry in entries:
        key = (entry.subject_code, entry.session_month, entry.session_year, entry.paper_variant)
        previous = seen.get(key)
        if previous is not None and previous != entry:
            raise ExamCalendarValidationError(
                f"Timetable disagrees with itself for {entry.subject_code}/"
                f"{entry.paper_variant} in {entry.session_month.value} {entry.session_year}"
            )
        seen[key] = entry


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "CalendarAvailability",
    "ExamCalendarError",
    "ExamCalendarService",
    "ExamCalendarValidationError",
    "ExamDateRow",
    "IngestResult",
    "PaperAvailability",
    "StudentExamCalendar",
    "StudentExamEntry",
    "TimetableEntry",
    "parse_timetable_payload",
]
