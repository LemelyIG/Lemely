"""Study-plan persistence, weekly regeneration, and completion (P4.7 chunk B).

Composes chunk A's pure scheduler (``lemely.core.study_plan.build_study_plan``)
with three live signals read straight off the database — never a second
weakness/placement/confidence engine. This module sits in ``lemely.db``,
outside the import-linter ``app > io > core`` layering contract
(``pyproject.toml`` ``[tool.importlinter]``), the same boundary
``lemely.db.flashcard_repo``/``lemely.db.practice_repo`` already sit at and
for the identical reason: it must compose a pure ``core`` algorithm with real
rows, and ``core`` may not import ``db``.

**Shape mirrors ``FlashcardService``/``PracticeService`` deliberately**: a
plain ``sessionmaker`` constructor argument, dataclass response types,
owner-scoped lookups, and — per D4.11's precedent, not D4.6's — **another
student's session id is a 404, not a 403**: a study plan is private study
material for exactly one student, so a 403 would be an existence oracle over
it. :class:`StudyPlanNotFoundError` and :class:`StudyPlanOwnershipError`
still exist as distinct types (both are tested); flattening both to 404 is
chunk C's job at the HTTP layer, not this module's.

**How the three signals are sourced (chunk A left them as plain core
dataclasses precisely so chunk B could map real rows onto them):**

1. **Weakness** — every ``WeaknessRecord`` row for the caller/subject,
   summed per topic across every attempt (mirrors
   :meth:`~lemely.db.practice_repo.PracticeService._weak_topics_for`'s
   aggregation, D4.10 §2), excluding a topic with zero net lost marks — the
   same "zero net lost marks is not a weakness" rule P4.5 applies.
2. **Placement** — the caller's most recently *marked* placement attempt for
   the subject (``Quiz.kind == placement``, owner-scoped on
   ``Quiz.student_id``, D4.6 §3's "``kind`` may only narrow an
   already-owner-scoped query"), read verbatim off its ``WeaknessRecord``
   rows exactly as :meth:`~lemely.db.placement_repo.PlacementService
   .get_result` does (D4.6 §6: no recomputation). No marked placement
   attempt for this subject means an empty signal, never an error — see the
   module docstring's honesty rules.
3. **Confidence** — every S-02 ``StudentConfidenceRating`` row for the
   caller's enrolment in this subject. No enrolment, or an enrolment with no
   ratings, is read as an empty signal (D4.9's lesson: an unanswered S-02
   field is "not answered", never treated as a restriction), not an error.

**Availability is measured against the live bank, not defaulted.**
:meth:`StudyPlanService._availability` counts real, visible
``question_bank`` rows (any source, for "practice earned"; ``past_paper``
source specifically, for "past-paper earned") and real
``flashcard_decks`` rows (for "flashcards earned") for exactly the topics
the three signals named — this is what makes chunk A's "activity type must
be earned" rule bind against reality instead of defaulting every topic to
``review``.

**Weekly regeneration supersedes, never mutates** — see
``lemely/db/models/study_plan.py``'s module docstring for the full
rationale. :func:`_week_start` is the one function that decides what "the
current week" means: the Monday of the ISO week containing the injected
``now`` (``now.date() - timedelta(days=now.weekday())``), computed off the
same clock the scheduler itself uses — a plan generated on any day of a week
and looked up on any other day of the *same* week resolves to the identical
row.

**XP is P5.** :class:`SessionView.completed_at` is the only seam this module
builds; nothing here computes or persists points, streaks, or XP events.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from lemely.core.schemas import WeakArea
from lemely.core.study_plan import (
    ConfidenceRating,
    PlacementTopicResult,
    TopicAvailability,
    build_study_plan,
)
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import QuestionSource, QuizKind, QuizSubmissionStatus
from lemely.db.models.flashcards import FlashcardDeck
from lemely.db.models.profiles import (
    StudentConfidenceRating,
    StudentProfile,
    StudentSubjectEnrolment,
)
from lemely.db.models.quizzes import QuestionBank, Quiz, QuizAssignment, QuizSubmission
from lemely.db.models.study_plan import StudyPlan as DbStudyPlan
from lemely.db.models.study_plan import StudyPlanActivityType as DbActivityType
from lemely.db.models.study_plan import StudyPlanSession as DbStudyPlanSession
from lemely.db.question_bank_repo import renderable_bank_filter, visible_bank_filter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from sqlalchemy.orm import Session, sessionmaker

#: Fallback weekly study budget when the caller has no ``StudentProfile
#: .weekly_study_hours`` set. Mirrors ``lemely.web.routers.student
#: ._DEFAULT_WEEKLY_HOURS`` — duplicated rather than imported because ``db``
#: must not depend on ``web`` (the layering runs the other way).
_DEFAULT_WEEKLY_HOURS = 11.0


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


def _week_start(now: datetime) -> date:
    """The Monday of the ISO week containing ``now`` — see the module docstring."""
    return now.date() - timedelta(days=now.weekday())


class StudyPlanError(Exception):
    """Base class for study-plan service failures."""


class StudyPlanNotFoundError(StudyPlanError):
    """No plan/session exists for the supplied id, anywhere (→ 404)."""


class StudyPlanOwnershipError(StudyPlanError):
    """The plan/session exists but belongs to another student.

    Kept as a distinct type from :class:`StudyPlanNotFoundError` — both are
    tested — even though chunk C renders both as a 404 (module docstring,
    D4.11 precedent).
    """


@dataclass(frozen=True, slots=True)
class SessionView:
    """One scheduled session, as persisted."""

    id: uuid.UUID
    date: date
    topic: str
    activity_type: DbActivityType
    duration_minutes: int
    focus: str
    completed_at: datetime | None
    subject_code: str
    """The owning plan's subject (P5.2 chunk B) — not part of the wire DTO
    (``lemely.web.routers.study_plan._session_to_dto`` doesn't read it); it
    exists so the web layer can award ``study_session_completed`` XP with the
    right subject attribution (D5.1 §7/D5.2) without a second query."""


@dataclass(frozen=True, slots=True)
class PlanView:
    """One persisted weekly plan and its sessions."""

    id: uuid.UUID
    student_id: uuid.UUID
    subject_code: str
    week_start: date
    weekly_hours: float
    available: bool
    reason: str | None
    generated_at: datetime
    sessions: list[SessionView]


class StudyPlanService:
    """Generate-and-persist, look up, and complete sessions of a weekly study plan.

    Constructed with a ``sessionmaker`` alone, mirroring
    :class:`~lemely.db.practice_repo.PracticeService` — every signal this
    service reads (weakness, placement, confidence, bank/deck availability)
    lives in the same database, so no second client is needed.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to a session factory and an optional clock."""
        self._sessionmaker = sessionmaker
        self._now = now

    # -- Generation (persist + weekly regeneration) --------------------------

    def generate(
        self,
        student_id: uuid.UUID | str,
        subject_code: str,
        *,
        weekly_hours: float | None = None,
        now: datetime | None = None,
    ) -> PlanView:
        """Build this week's plan from the three live signals and persist it.

        Supersedes (never mutates) any existing active plan for the same
        ``(student, subject, week)`` — see the module docstring. Persists
        even a ``no_signal`` refusal, so "the student has no plan generated
        yet this week" and "the student was refused a plan this week" are
        both real, queryable states via :meth:`get_current`.

        ``weekly_hours`` defaults to the caller's ``StudentProfile
        .weekly_study_hours`` when omitted, falling back to
        :data:`_DEFAULT_WEEKLY_HOURS` when the caller has no profile row or
        left it unset.
        """
        student_uuid = _as_uuid(student_id)
        moment = now if now is not None else self._now()
        week_start = _week_start(moment)

        with self._sessionmaker() as session, session.begin():
            weaknesses = self._weaknesses(session, student_uuid, subject_code)
            placement_results = self._placement_results(session, student_uuid, subject_code)
            confidence_ratings = self._confidence_ratings(session, student_uuid, subject_code)
            resolved_hours = (
                weekly_hours
                if weekly_hours is not None
                else self._weekly_hours(session, student_uuid)
            )
            topics = (
                {w.topic for w in weaknesses}
                | {p.topic for p in placement_results}
                | {c.topic for c in confidence_ratings}
            )
            availability = self._availability(session, student_uuid, subject_code, topics)

            plan = build_study_plan(
                str(student_uuid),
                subject_code,
                weekly_hours=resolved_hours,
                now=moment,
                weaknesses=weaknesses,
                placement_results=placement_results,
                confidence_ratings=confidence_ratings,
                availability=availability,
            )

            existing = session.scalars(
                select(DbStudyPlan).where(
                    DbStudyPlan.user_id == student_uuid,
                    DbStudyPlan.subject_code == subject_code,
                    DbStudyPlan.week_start == week_start,
                    DbStudyPlan.superseded_at.is_(None),
                )
            ).first()
            if existing is not None:
                existing.superseded_at = moment

            row = DbStudyPlan(
                user_id=student_uuid,
                subject_code=subject_code,
                week_start=week_start,
                weekly_hours=resolved_hours,
                available=plan.available,
                reason=plan.reason,
                generated_at=moment,
            )
            session.add(row)
            session.flush()

            session_rows = [
                DbStudyPlanSession(
                    plan_id=row.id,
                    date=s.date,
                    topic=s.topic,
                    activity_type=DbActivityType(s.activity_type.value),
                    duration_minutes=s.duration_minutes,
                    focus=s.focus,
                )
                for s in plan.sessions
            ]
            for session_row in session_rows:
                session.add(session_row)
            session.flush()

            return self._to_view(row, session_rows)

    # -- Lookup -----------------------------------------------------------------

    def get_current(
        self, student_id: uuid.UUID | str, subject_code: str, *, now: datetime | None = None
    ) -> PlanView | None:
        """The active plan for this week, or ``None`` if none has been generated yet."""
        student_uuid = _as_uuid(student_id)
        moment = now if now is not None else self._now()
        week_start = _week_start(moment)
        with self._sessionmaker() as session:
            row = session.scalars(
                select(DbStudyPlan).where(
                    DbStudyPlan.user_id == student_uuid,
                    DbStudyPlan.subject_code == subject_code,
                    DbStudyPlan.week_start == week_start,
                    DbStudyPlan.superseded_at.is_(None),
                )
            ).first()
            if row is None:
                return None
            sessions = session.scalars(
                select(DbStudyPlanSession)
                .where(DbStudyPlanSession.plan_id == row.id)
                .order_by(DbStudyPlanSession.date, DbStudyPlanSession.created_at)
            ).all()
            return self._to_view(row, sessions)

    # -- Completion ---------------------------------------------------------------

    def complete_session(
        self,
        student_id: uuid.UUID | str,
        session_id: uuid.UUID | str,
        *,
        now: datetime | None = None,
    ) -> SessionView:
        """Mark one of the caller's own sessions complete.

        Idempotent: completing an already-completed session leaves its
        original ``completed_at`` untouched rather than moving it forward —
        a completion record is a true record of *when it happened*, not of
        the most recent time someone re-clicked it.

        Raises:
            StudyPlanNotFoundError: no session exists with ``session_id``,
                anywhere (404).
            StudyPlanOwnershipError: it exists but is not the caller's — the
                caller still gets a distinct typed error; chunk C renders it
                as a 404 too (module docstring).
        """
        student_uuid = _as_uuid(student_id)
        session_uuid = _as_uuid(session_id)
        moment = now if now is not None else self._now()
        with self._sessionmaker() as session, session.begin():
            row, plan = self._owned_session(session, student_uuid, session_uuid)
            if row.completed_at is None:
                row.completed_at = moment
            session.flush()
            return self._to_session_view(row, plan.subject_code)

    # -- Internals ----------------------------------------------------------------

    def _owned_session(
        self, session: Session, student_uuid: uuid.UUID, session_uuid: uuid.UUID
    ) -> tuple[DbStudyPlanSession, DbStudyPlan]:
        row = session.get(DbStudyPlanSession, session_uuid)
        if row is None:
            raise StudyPlanNotFoundError(f"Unknown study-plan session: {session_uuid}")
        plan = session.get(DbStudyPlan, row.plan_id)
        if plan is None or plan.user_id != student_uuid:
            raise StudyPlanOwnershipError(
                f"Study-plan session {session_uuid} is not owned by student {student_uuid}"
            )
        return row, plan

    def _weaknesses(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> list[WeakArea]:
        """Every ``WeaknessRecord`` row, summed per topic across every attempt.

        Mirrors :meth:`~lemely.db.practice_repo.PracticeService
        ._weak_topics_for`'s aggregation (D4.10 §2) but keeps the summed
        marks rather than reducing to topic names, and excludes a topic with
        zero net lost marks — the same "zero net lost marks is not a
        weakness" rule.
        """
        rows = session.execute(
            select(WeaknessRecord.topic, WeaknessRecord.lost_marks, WeaknessRecord.maximum_marks)
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid, Attempt.subject_code == subject_code)
        ).all()
        totals: dict[str, list[int]] = {}
        for topic, lost, maximum in rows:
            bucket = totals.setdefault(topic, [0, 0])
            bucket[0] += lost
            bucket[1] += maximum
        return [
            WeakArea(
                topic=topic,
                lost_marks=lost,
                maximum_marks=maximum,
                accuracy=(1.0 - lost / maximum) if maximum > 0 else 1.0,
                question_ids=[],
            )
            for topic, (lost, maximum) in totals.items()
            if lost > 0
        ]

    def _placement_results(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> list[PlacementTopicResult]:
        """The caller's most recently *marked* placement attempt's topic breakdown.

        Owner-scoped on ``Quiz.student_id`` first, ``kind``/``subject_code``
        narrowing on top (D4.6 §3) — mirrors
        :meth:`~lemely.db.placement_repo.PlacementService.get_result`'s
        marked branch, but finds the latest attempt instead of reading one
        named by ``assignment_id``. No marked placement attempt for this
        subject returns an empty list, never an error.
        """
        latest_attempt_id = session.scalar(
            select(QuizSubmission.attempt_id)
            .join(QuizAssignment, QuizAssignment.id == QuizSubmission.assignment_id)
            .join(Quiz, Quiz.id == QuizAssignment.quiz_id)
            .where(
                Quiz.student_id == student_uuid,
                Quiz.kind == QuizKind.placement,
                Quiz.subject_code == subject_code,
                QuizSubmission.status == QuizSubmissionStatus.marked,
                QuizSubmission.attempt_id.is_not(None),
            )
            .order_by(QuizSubmission.marked_at.desc())
            .limit(1)
        )
        if latest_attempt_id is None:
            return []
        rows = session.scalars(
            select(WeaknessRecord).where(WeaknessRecord.attempt_id == latest_attempt_id)
        ).all()
        return [
            PlacementTopicResult(
                topic=w.topic, lost_marks=w.lost_marks, maximum_marks=w.maximum_marks
            )
            for w in rows
        ]

    def _confidence_ratings(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> list[ConfidenceRating]:
        """Every S-02 confidence rating for the caller's enrolment in ``subject_code``.

        No enrolment, or an enrolment with no ratings, is an empty list, not
        an error — D4.9's "an unanswered S-02 field is *not answered*, never
        a restriction" lesson, applied to the read instead of a filter.
        """
        rows = session.execute(
            select(StudentConfidenceRating.topic, StudentConfidenceRating.rating)
            .join(
                StudentSubjectEnrolment,
                StudentSubjectEnrolment.id == StudentConfidenceRating.enrolment_id,
            )
            .where(
                StudentSubjectEnrolment.user_id == student_uuid,
                StudentSubjectEnrolment.subject_code == subject_code,
            )
        ).all()
        return [ConfidenceRating(topic=topic, rating=rating) for topic, rating in rows]

    def _weekly_hours(self, session: Session, student_uuid: uuid.UUID) -> float:
        hours = session.scalar(
            select(StudentProfile.weekly_study_hours).where(StudentProfile.user_id == student_uuid)
        )
        return float(hours) if hours else _DEFAULT_WEEKLY_HOURS

    def _availability(
        self,
        session: Session,
        student_uuid: uuid.UUID,
        subject_code: str,
        topics: set[str],
    ) -> dict[str, TopicAvailability]:
        """Real practice/past-paper counts and flashcard-deck presence, per topic.

        Built on :func:`~lemely.db.question_bank_repo.visible_bank_filter` —
        the same §1.3 visibility predicate ``PracticeService`` uses — plus
        :func:`~lemely.db.question_bank_repo.renderable_bank_filter` (P4.8
        chunk 0), so "available" here means the same thing it means to the
        practice surface a scheduled ``practice``/``past_paper`` session
        would actually route to, including never counting a figure-dependent
        row the practice surface would itself refuse to serve.
        """
        if not topics:
            return {}
        practice_counts: dict[str, int] = {
            topic: count
            for topic, count in session.execute(
                select(QuestionBank.topic, func.count())
                .where(
                    QuestionBank.is_active.is_(True),
                    visible_bank_filter(student_uuid, ()),
                    renderable_bank_filter(),
                    QuestionBank.subject_code == subject_code,
                    QuestionBank.topic.in_(topics),
                )
                .group_by(QuestionBank.topic)
            ).all()
            if topic is not None
        }
        past_paper_counts: dict[str, int] = {
            topic: count
            for topic, count in session.execute(
                select(QuestionBank.topic, func.count())
                .where(
                    QuestionBank.is_active.is_(True),
                    visible_bank_filter(student_uuid, ()),
                    renderable_bank_filter(),
                    QuestionBank.subject_code == subject_code,
                    QuestionBank.source == QuestionSource.past_paper,
                    QuestionBank.topic.in_(topics),
                )
                .group_by(QuestionBank.topic)
            ).all()
            if topic is not None
        }
        deck_topics = set(
            session.scalars(
                select(FlashcardDeck.topic)
                .where(
                    FlashcardDeck.user_id == student_uuid,
                    FlashcardDeck.subject_code == subject_code,
                    FlashcardDeck.topic.in_(topics),
                )
                .distinct()
            ).all()
        )
        return {
            topic: TopicAvailability(
                practice_question_count=practice_counts.get(topic, 0),
                past_paper_question_count=past_paper_counts.get(topic, 0),
                has_flashcard_deck=topic in deck_topics,
            )
            for topic in topics
        }

    def _to_view(self, row: DbStudyPlan, sessions: Iterable[DbStudyPlanSession]) -> PlanView:
        return PlanView(
            id=row.id,
            student_id=row.user_id,
            subject_code=row.subject_code,
            week_start=row.week_start,
            weekly_hours=row.weekly_hours,
            available=row.available,
            reason=row.reason,
            generated_at=row.generated_at,
            sessions=[self._to_session_view(s, row.subject_code) for s in sessions],
        )

    def _to_session_view(self, row: DbStudyPlanSession, subject_code: str) -> SessionView:
        return SessionView(
            id=row.id,
            date=row.date,
            topic=row.topic,
            activity_type=row.activity_type,
            duration_minutes=row.duration_minutes,
            focus=row.focus,
            completed_at=row.completed_at,
            subject_code=subject_code,
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "PlanView",
    "SessionView",
    "StudyPlanError",
    "StudyPlanNotFoundError",
    "StudyPlanOwnershipError",
    "StudyPlanService",
]
