"""Student onboarding profile service (P4.3 chunk B, D4.5).

Backs the onboarding questionnaire (S-01/S-02) and, later, chunk C's
``targets_for`` feed into ``lemely.core.at_risk``'s per-subject target-grade
rule. A student's profile has no cross-tenant ownership question — tenancy
is just "``auth.user_id`` == the row's ``user_id``" — enforced entirely at
the router layer (``lemely.web.routers.me``), the same way
:class:`~lemely.db.notification_prefs_repo.NotificationPreferencesService`
is: this service takes ``user_id`` as a plain method argument, never a
composed ownership check.

``UNSET``/``_UnsetType`` are imported from
:mod:`lemely.db.notification_prefs_repo` rather than redeclared here — both
modules need the identical "omitted vs explicit None" sentinel for PATCH
semantics, and importing it keeps exactly one sentinel type in the codebase
instead of two structurally-identical-but-distinct ones (an
``isinstance(x, _UnsetType)`` check from one module would silently fail
against the other's sentinel). The import runs db-module-to-db-module, the
same direction already established throughout this package (see
``lemely.db.review_repo`` importing from ``lemely.db.class_repo``), so it is
not a new coupling direction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lemely.core.history import GRADE_ORDER
from lemely.db.models.academic import Subject
from lemely.db.models.enums import QualificationLevel, SessionMonth
from lemely.db.models.profiles import (
    StudentConfidenceRating,
    StudentEnrolmentPaper,
    StudentProfile,
    StudentSubjectEnrolment,
)
from lemely.db.notification_prefs_repo import UNSET, _UnsetType

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker


class StudentProfileError(Exception):
    """Base class for student-profile-model failures."""


class StudentProfileNotFoundError(StudentProfileError):
    """No profile/enrolment/rating exists for the given user (→ 404)."""


class StudentProfileValidationError(StudentProfileError):
    """Supplied data fails validation: unknown grade/subject, out-of-range value (→ 422)."""


@dataclass(frozen=True, slots=True)
class StudentProfileRow:
    """One student's onboarding profile (S-02 whole-person facts)."""

    user_id: uuid.UUID
    qualification_level: QualificationLevel | None
    grade_level: str | None
    school_name: str | None
    has_external_lessons: bool | None
    weekly_study_hours: int | None
    onboarding_completed_at: datetime | None
    leaderboard_opt_out: bool
    """D5.1 §9: mirrors :attr:`~lemely.db.models.profiles.StudentProfile.leaderboard_opt_out`
    verbatim -- ``False`` unless the student has explicitly opted out."""


@dataclass(frozen=True, slots=True)
class SubjectEnrolmentRow:
    """One (student, subject) enrolment, with its paper numbers (S-01)."""

    enrolment_id: uuid.UUID
    user_id: uuid.UUID
    subject_code: str
    target_grade: str | None
    session_month: SessionMonth | None
    session_year: int | None
    papers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ConfidenceRatingRow:
    """One (enrolment, topic) self-assessment slider value, 1..5."""

    enrolment_id: uuid.UUID
    topic: str
    rating: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StudentProfileService:
    """Onboarding-profile CRUD: profile scalars, enrolments, papers, confidence ratings.

    Constructed with a ``sessionmaker`` alone (mirroring
    :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesService`)
    plus an injected ``now`` clock (mirroring
    :class:`~lemely.db.quiz_taking_repo.QuizTakingService`) so
    :meth:`mark_onboarding_complete`'s default timestamp is testable without
    sleeping or mutating the wall clock.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to a session factory and an optional clock."""
        self._sessionmaker = sessionmaker
        self._now = now

    # -- Profile ---------------------------------------------------------

    def get_or_create_profile(self, user_id: uuid.UUID | str) -> StudentProfileRow:
        """Return ``user_id``'s profile, creating a bare (all-NULL) row on first call.

        Unlike :meth:`~lemely.db.notification_prefs_repo.NotificationPreferencesService.get`
        (which never creates a row), this **does** create one — deliberately.
        Onboarding needs a real row to attach enrolments to via
        :class:`~lemely.db.models.profiles.StudentSubjectEnrolment.user_id`'s
        FK to ``users.id`` (not to this row, but conceptually the profile is
        the anchor a student's onboarding data hangs off), whereas
        notification prefs has no child table depending on its existence at
        all — "absent row reads as defaults" is sufficient there. A GET-only
        caller of this method (see ``lemely.web.routers.me``) accepts this
        write side effect explicitly; see that route's docstring.
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            row = session.get(StudentProfile, uid)
            if row is not None:
                return _profile_row(row)
            row = StudentProfile(user_id=uid)
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                # Lost a race with a concurrent get_or_create_profile call;
                # the other writer's row is now there.
                session.rollback()
                row = session.get(StudentProfile, uid)
                assert row is not None  # noqa: S101 - guaranteed by the FK/PK we just lost the race on
            else:
                session.refresh(row)
            return _profile_row(row)

    def update_profile(
        self,
        user_id: uuid.UUID | str,
        *,
        qualification_level: QualificationLevel | str | _UnsetType | None = UNSET,
        grade_level: str | _UnsetType | None = UNSET,
        school_name: str | _UnsetType | None = UNSET,
        has_external_lessons: bool | _UnsetType | None = UNSET,
        weekly_study_hours: int | _UnsetType | None = UNSET,
        leaderboard_opt_out: bool | _UnsetType = UNSET,
    ) -> StudentProfileRow:
        """Partially update ``user_id``'s profile. Keywords left at :data:`UNSET` are untouched.

        Materialises the row first (:meth:`get_or_create_profile`) so a
        first-ever PATCH from a brand-new user still lands. An explicit
        ``None`` clears a field (every field here is nullable/skippable per
        S-02); omission (:data:`UNSET`) leaves it as-is.

        ``leaderboard_opt_out`` is boolean, never nullable (D5.1 §9 — the
        column itself is ``NOT NULL``), so it takes no ``None`` branch: an
        explicit request either sets it ``True``/``False`` or omits it
        entirely. Losslessly reversible — no XP history is touched by this
        call, so flipping it back restores the exact previous ranked
        position (``lemely.db.leaderboard_repo`` reads the flag live on
        every board, never a snapshot).

        Raises:
            StudentProfileValidationError: ``weekly_study_hours`` is supplied
                and outside 0..80, or ``qualification_level`` is supplied as
                a string that is not a valid :class:`QualificationLevel`
                member.
        """
        uid = _as_uuid(user_id)
        if (
            not isinstance(weekly_study_hours, _UnsetType)
            and weekly_study_hours is not None
            and not (0 <= weekly_study_hours <= 80)
        ):
            raise StudentProfileValidationError(
                f"weekly_study_hours must be between 0 and 80, got {weekly_study_hours!r}"
            )
        resolved_qualification: QualificationLevel | _UnsetType | None
        if isinstance(qualification_level, str):
            try:
                resolved_qualification = QualificationLevel(qualification_level)
            except ValueError as exc:
                raise StudentProfileValidationError(
                    f"Unknown qualification level: {qualification_level!r}"
                ) from exc
        else:
            resolved_qualification = qualification_level

        self.get_or_create_profile(uid)
        with self._sessionmaker() as session, session.begin():
            row = session.get(StudentProfile, uid, with_for_update=True)
            assert row is not None  # noqa: S101 - just materialised above
            if not isinstance(resolved_qualification, _UnsetType):
                row.qualification_level = resolved_qualification
            if not isinstance(grade_level, _UnsetType):
                row.grade_level = grade_level
            if not isinstance(school_name, _UnsetType):
                row.school_name = school_name
            if not isinstance(has_external_lessons, _UnsetType):
                row.has_external_lessons = has_external_lessons
            if not isinstance(weekly_study_hours, _UnsetType):
                row.weekly_study_hours = weekly_study_hours
            if not isinstance(leaderboard_opt_out, _UnsetType):
                row.leaderboard_opt_out = leaderboard_opt_out
            session.flush()
            return _profile_row(row)

    def mark_onboarding_complete(
        self, user_id: uuid.UUID | str, *, completed_at: datetime | None = None
    ) -> StudentProfileRow:
        """Set ``onboarding_completed_at`` (defaults to the injected clock's ``now``)."""
        uid = _as_uuid(user_id)
        when = completed_at if completed_at is not None else self._now()
        self.get_or_create_profile(uid)
        with self._sessionmaker() as session, session.begin():
            row = session.get(StudentProfile, uid, with_for_update=True)
            assert row is not None  # noqa: S101 - just materialised above
            row.onboarding_completed_at = when
            session.flush()
            return _profile_row(row)

    # -- Enrolments --------------------------------------------------------

    def list_enrolments(self, user_id: uuid.UUID | str) -> list[SubjectEnrolmentRow]:
        """Return every subject enrolment for ``user_id``, with paper numbers."""
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            rows = session.scalars(
                select(StudentSubjectEnrolment)
                .where(StudentSubjectEnrolment.user_id == uid)
                .order_by(StudentSubjectEnrolment.subject_code)
            ).all()
            return [self._enrolment_row(session, row) for row in rows]

    def upsert_enrolment(
        self,
        user_id: uuid.UUID | str,
        subject_code: str,
        *,
        target_grade: str | _UnsetType | None = UNSET,
        session_month: SessionMonth | _UnsetType | None = UNSET,
        session_year: int | _UnsetType | None = UNSET,
    ) -> SubjectEnrolmentRow:
        """Create or partially update the ``(user_id, subject_code)`` enrolment.

        Raises:
            StudentProfileValidationError: ``subject_code`` does not exist in
                ``subjects``, or ``target_grade`` is supplied and not a
                member of :data:`~lemely.core.history.GRADE_ORDER`.
        """
        uid = _as_uuid(user_id)
        if (
            not isinstance(target_grade, _UnsetType)
            and target_grade is not None
            and target_grade not in GRADE_ORDER
        ):
            raise StudentProfileValidationError(f"Unknown target grade: {target_grade!r}")
        with self._sessionmaker() as session, session.begin():
            subject_exists = session.scalars(
                select(Subject.code).where(Subject.code == subject_code)
            ).first()
            if subject_exists is None:
                raise StudentProfileValidationError(f"Unknown subject code: {subject_code!r}")
            row = session.scalars(
                select(StudentSubjectEnrolment).where(
                    StudentSubjectEnrolment.user_id == uid,
                    StudentSubjectEnrolment.subject_code == subject_code,
                )
            ).first()
            if row is None:
                row = StudentSubjectEnrolment(user_id=uid, subject_code=subject_code)
                session.add(row)
            if not isinstance(target_grade, _UnsetType):
                row.target_grade = target_grade
            if not isinstance(session_month, _UnsetType):
                row.session_month = session_month
            if not isinstance(session_year, _UnsetType):
                row.session_year = session_year
            session.flush()
            return self._enrolment_row(session, row)

    def delete_enrolment(self, user_id: uuid.UUID | str, subject_code: str) -> None:
        """Delete the caller's enrolment for ``subject_code`` (papers/ratings cascade).

        Raises:
            StudentProfileNotFoundError: No such enrolment for this user —
                checked by ``user_id`` ownership, never by a bare enrolment
                id, so a caller cannot delete another student's enrolment.
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            row = self._owned_enrolment(session, uid, subject_code)
            session.delete(row)

    def set_enrolment_papers(
        self, user_id: uuid.UUID | str, subject_code: str, paper_numbers: Sequence[int]
    ) -> SubjectEnrolmentRow:
        """Full-replace the paper-number set for one enrolment (PUT semantics).

        Raises:
            StudentProfileNotFoundError: No such enrolment for this user.
        """
        uid = _as_uuid(user_id)
        wanted = set(paper_numbers)
        with self._sessionmaker() as session, session.begin():
            enrolment = self._owned_enrolment(session, uid, subject_code)
            existing = {
                p.paper_number: p
                for p in session.scalars(
                    select(StudentEnrolmentPaper).where(
                        StudentEnrolmentPaper.enrolment_id == enrolment.id
                    )
                ).all()
            }
            for number, paper_row in existing.items():
                if number not in wanted:
                    session.delete(paper_row)
            for number in wanted - existing.keys():
                session.add(StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=number))
            session.flush()
            return self._enrolment_row(session, enrolment)

    # -- Confidence ratings --------------------------------------------------

    def list_confidence_ratings(
        self, user_id: uuid.UUID | str, subject_code: str
    ) -> list[ConfidenceRatingRow]:
        """Return every confidence rating for one enrolment.

        Raises:
            StudentProfileNotFoundError: No such enrolment for this user.
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            enrolment = self._owned_enrolment(session, uid, subject_code)
            rows = session.scalars(
                select(StudentConfidenceRating)
                .where(StudentConfidenceRating.enrolment_id == enrolment.id)
                .order_by(StudentConfidenceRating.topic)
            ).all()
            return [
                ConfidenceRatingRow(enrolment_id=r.enrolment_id, topic=r.topic, rating=r.rating)
                for r in rows
            ]

    def set_confidence_ratings(
        self, user_id: uuid.UUID | str, subject_code: str, ratings: Mapping[str, int]
    ) -> list[ConfidenceRatingRow]:
        """Full-replace the topic->rating map for one enrolment (PUT semantics).

        Raises:
            StudentProfileValidationError: One or more ratings are outside
                1..5 — every invalid topic is collected into one error
                message rather than failing on the first.
            StudentProfileNotFoundError: No such enrolment for this user.
        """
        invalid = {topic: value for topic, value in ratings.items() if not (1 <= value <= 5)}
        if invalid:
            bad = ", ".join(f"{topic!r}={value!r}" for topic, value in invalid.items())
            raise StudentProfileValidationError(
                f"Ratings must be between 1 and 5 (inclusive): {bad}"
            )
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            enrolment = self._owned_enrolment(session, uid, subject_code)
            existing = {
                r.topic: r
                for r in session.scalars(
                    select(StudentConfidenceRating).where(
                        StudentConfidenceRating.enrolment_id == enrolment.id
                    )
                ).all()
            }
            for topic, rating_row in existing.items():
                if topic not in ratings:
                    session.delete(rating_row)
            for topic, value in ratings.items():
                if topic in existing:
                    existing[topic].rating = value
                else:
                    session.add(
                        StudentConfidenceRating(
                            enrolment_id=enrolment.id, topic=topic, rating=value
                        )
                    )
            session.flush()
            rows = session.scalars(
                select(StudentConfidenceRating)
                .where(StudentConfidenceRating.enrolment_id == enrolment.id)
                .order_by(StudentConfidenceRating.topic)
            ).all()
            return [
                ConfidenceRatingRow(enrolment_id=r.enrolment_id, topic=r.topic, rating=r.rating)
                for r in rows
            ]

    # -- At-risk feed ---------------------------------------------------------

    def target_grades_for(self, user_id: uuid.UUID | str) -> dict[str, str]:
        """Return ``subject_code -> target_grade`` for every non-null-target enrolment.

        Feeds directly into ``lemely.core.at_risk.assess_at_risk``'s
        ``targets: Mapping[str, str] | None`` parameter (D4.5, chunk C — not
        built here). An enrolment with no target grade is skipped, never
        included with a placeholder: D4.5 requires that a subject with no
        target reads as "not evaluable", not "cleared".
        """
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(StudentSubjectEnrolment.subject_code, StudentSubjectEnrolment.target_grade)
                .where(StudentSubjectEnrolment.user_id == uid)
                .where(StudentSubjectEnrolment.target_grade.is_not(None))
            ).all()
            return {subject_code: target_grade for subject_code, target_grade in rows}

    def target_grades_for_many(
        self, user_ids: Iterable[uuid.UUID | str]
    ) -> dict[str, dict[str, str]]:
        """Bulk form of :meth:`target_grades_for`.

        Returns ``user_id (str) -> subject_code -> target_grade``.

        One query for every student in the caller's roster/class rather than one
        query per student in a loop (D4.5, chunk C) — teacher and parent routes
        assess many students at once, and an N+1 there would scale with class
        size on every dashboard load. A student with no enrolments, or none with
        a target grade set, simply has no key in the returned mapping rather
        than an empty-dict placeholder, so callers can use plain ``.get(uid, {})``.
        """
        uids = {_as_uuid(uid) for uid in user_ids}
        if not uids:
            return {}
        with self._sessionmaker() as session:
            rows = session.execute(
                select(
                    StudentSubjectEnrolment.user_id,
                    StudentSubjectEnrolment.subject_code,
                    StudentSubjectEnrolment.target_grade,
                )
                .where(StudentSubjectEnrolment.user_id.in_(uids))
                .where(StudentSubjectEnrolment.target_grade.is_not(None))
            ).all()
        result: dict[str, dict[str, str]] = {}
        for user_id, subject_code, target_grade in rows:
            result.setdefault(str(user_id), {})[subject_code] = target_grade
        return result

    # -- Internals ------------------------------------------------------------

    def _owned_enrolment(
        self, session: Session, uid: uuid.UUID, subject_code: str
    ) -> StudentSubjectEnrolment:
        row = session.scalars(
            select(StudentSubjectEnrolment).where(
                StudentSubjectEnrolment.user_id == uid,
                StudentSubjectEnrolment.subject_code == subject_code,
            )
        ).first()
        if row is None:
            raise StudentProfileNotFoundError(
                f"No enrolment for user {uid} in subject {subject_code!r}"
            )
        return row

    def _enrolment_row(
        self, session: Session, enrolment: StudentSubjectEnrolment
    ) -> SubjectEnrolmentRow:
        papers = session.scalars(
            select(StudentEnrolmentPaper.paper_number)
            .where(StudentEnrolmentPaper.enrolment_id == enrolment.id)
            .order_by(StudentEnrolmentPaper.paper_number)
        ).all()
        return SubjectEnrolmentRow(
            enrolment_id=enrolment.id,
            user_id=enrolment.user_id,
            subject_code=enrolment.subject_code,
            target_grade=enrolment.target_grade,
            session_month=enrolment.session_month,
            session_year=enrolment.session_year,
            papers=tuple(papers),
        )


def _profile_row(model: StudentProfile) -> StudentProfileRow:
    return StudentProfileRow(
        user_id=model.user_id,
        qualification_level=model.qualification_level,
        grade_level=model.grade_level,
        school_name=model.school_name,
        has_external_lessons=model.has_external_lessons,
        weekly_study_hours=model.weekly_study_hours,
        onboarding_completed_at=model.onboarding_completed_at,
        leaderboard_opt_out=model.leaderboard_opt_out,
    )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


def enrolled_paper_numbers(
    session: Session, student_uuid: uuid.UUID, subject_code: str
) -> frozenset[int]:
    """Paper numbers this student's onboarding says they will sit for ``subject_code``.

    Shared by :class:`~lemely.db.placement_repo.PlacementService` and
    :class:`~lemely.db.practice_repo.PracticeService` — D4.9's lesson
    ("narrow to the papers the student will sit; empty means *not answered*,
    never *sits no papers*") applies identically to both surfaces, so the
    lookup lives here once rather than being copy-pasted into each. A caller
    with no ``student_enrolment_papers`` rows for this subject gets back an
    empty ``frozenset`` and must **not** treat that as a restriction — see
    D4.6 §5 / D4.9 for why an unanswered S-02 question means "not narrowed",
    not "sits nothing".
    """
    numbers = session.scalars(
        select(StudentEnrolmentPaper.paper_number)
        .join(
            StudentSubjectEnrolment,
            StudentSubjectEnrolment.id == StudentEnrolmentPaper.enrolment_id,
        )
        .where(
            StudentSubjectEnrolment.user_id == student_uuid,
            StudentSubjectEnrolment.subject_code == subject_code,
        )
    ).all()
    return frozenset(numbers)


__all__ = [
    "ConfidenceRatingRow",
    "StudentProfileError",
    "StudentProfileNotFoundError",
    "StudentProfileRow",
    "StudentProfileService",
    "StudentProfileValidationError",
    "SubjectEnrolmentRow",
    "enrolled_paper_numbers",
]
