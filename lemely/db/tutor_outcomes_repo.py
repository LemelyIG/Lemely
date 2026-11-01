"""Past-student outcome figures from the database: SP4 and T8 (SPEC §b.2, §e.3; ADR-T04).

The rules are ``core.tutor_outcomes``'s; this module gathers their inputs in
**three statements, in one transaction**, and computes nothing else:

1. **Profile check + subject names.** The tutor must be visible to the caller
   (SP4: listed and not paused, with no active block between a student caller
   and the tutor, through the shared predicates, as SP2 checks it; T8: listed or
   in review, paused or not, SPEC §a.4b ID-7). The same row brings the tutor's
   subjects (one figure pair each) and the database ``now()``, the one instant
   every later comparison uses: ``now()`` is fixed for the transaction, so the
   cohort statement's membership predicate and the core's windows, close
   instants and hold read the same clock.
2. **Cohort.** One row per (subject, student) with a counted session
   (``tutoring_predicates.OUTCOME_MEMBERSHIP_SQL``: ``accepted_at IS NOT NULL``,
   ``accepted``/``completed``/``no_show``, ended): ``S`` (the first counted
   session's start) and the facts the core needs, read explicitly from
   ``users`` (``email_verified_at``, which keeps the **first** verification,
   ``lemely/auth/mirror.py``; ``created_at``), ``student_tutoring_preferences``
   (an absent row is "counted, never changed"), ``tutoring_blocks`` through the
   shared predicates only (any student-to-tutor block, removed ones included:
   ``student_ever_blocked_tutor_sql`` excludes, and
   ``student_block_of_tutor_created_at_sql`` dates the hold) and
   ``tutor_data_grants`` (any row for the pair, live or revoked). Eligibility and
   the hold are then decided by ``is_member_eligible`` and ``is_recent_change``
   themselves, so they cannot drift from the core; the parity test pins the
   statement that feeds them.
3. **Observations.** Exact-boundary past-paper grades on the ladder, in the
   figure's subject, not deleted (:func:`outcome_eligible_attempt_sql`, the SQL
   mirror of ``is_outcome_eligible``), recorded in ``[S - 180 d, S + 120 d)``.
   Only the **published** members' grades are read: a subject whose figures the
   hold hides, an ineligible student and a member whose window is still open
   never have a grade loaded. With no published member anywhere the statement
   is skipped.

**Explicit predicates.** Every statement is ``sqlalchemy.text`` and states its
own filters (``deleted_at IS NULL`` included): the soft-delete loader criterion
of ``lemely/db/session.py`` applies to ORM entity selects only and is never
relied on here (F9).

**Elapsed time.** Window bounds are bound as seconds through
``make_interval(secs => ...)``; ``interval '120 days'`` (or a ``timedelta``,
which psycopg sends as days) is wall-clock arithmetic in a Cairo session and
would move by an hour across 29 October (SPEC §i.5, §i.7).

**Nothing is cached** (decision row 13): every call reads the database again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.core.history import GRADE_ORDER
from lemely.core.tutor_outcomes import (
    BEFORE_LOOKBACK,
    DURING_WINDOW,
    OUTCOME_K_MIN,
    CohortMember,
    GradeObservation,
    SubjectOutcome,
    is_member_eligible,
    is_recent_change,
    outcome_for_subject,
    published_members,
)
from lemely.db.models.enums import AttemptOrigin, BoundarySource, Role, TutorListingState
from lemely.db.tutor_directory_repo import SubjectRef, TutorProfileView, fetch_profile_view
from lemely.db.tutoring_predicates import (
    OUTCOME_MEMBERSHIP_SQL,
    active_block_between_sql,
    listed_and_not_paused_sql,
    student_block_of_tutor_created_at_sql,
    student_ever_blocked_tutor_sql,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.orm import Session, sessionmaker

#: The recorded ladder (ADR-T04; decision row 19): A* to E, then U.
LADDER: Final[tuple[str, ...]] = tuple(GRADE_ORDER)

#: Listing states whose own preview shows outcomes (T8, SPEC §a.4b ID-7), as a SQL list.
_PREVIEW_STATES_SQL: Final = (
    f"('{TutorListingState.listed.value}', '{TutorListingState.pending_review.value}')"
)

_ALIAS: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: ``alias.column`` or ``:bind``, as the shared predicates accept.
_QUALIFIED_OR_PARAM: Final = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*|:[A-Za-z_][A-Za-z0-9_]*"
)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortEntry:
    """One cohort member: the core's :class:`CohortMember` and whose it is.

    ``student_id`` and ``subject_code`` stay in this module (they pick the
    member's observations); the core and every DTO see only the opaque ``ref``.
    """

    subject_code: str
    student_id: uuid.UUID
    member: CohortMember


@dataclass(frozen=True, slots=True)
class SubjectFigures:
    """Both figures for one of the tutor's subjects."""

    subject: SubjectRef
    outcome: SubjectOutcome


@dataclass(frozen=True, slots=True)
class TutorOutcomes:
    """A tutor's figures, one entry per subject they teach, by subject name."""

    tutor_id: uuid.UUID
    ladder: tuple[str, ...]
    subjects: tuple[SubjectFigures, ...]


@dataclass(frozen=True, slots=True)
class TutorPreview:
    """T8: the profile as students see it, and the figures while listed or in review."""

    profile: TutorProfileView
    outcomes: TutorOutcomes | None


@dataclass(frozen=True, slots=True)
class _ProfileCheck:
    tutor_id: uuid.UUID
    tutor_user_id: uuid.UUID
    db_now: datetime
    subjects: tuple[SubjectRef, ...]


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------


def outcome_eligible_attempt_sql(attempt_alias: str, subject_operand: str) -> str:
    """The SQL mirror of ``core.tutor_outcomes.is_outcome_eligible`` for one ``attempts`` row.

    ``attempt_alias`` names the row; ``subject_operand`` is the figure's subject,
    a qualified column (``c.subject_code``) or a bind parameter (``:subject``).
    The ladder is the bind parameter ``:ladder`` (a list of grades). Like the
    core: a past paper, graded on the ladder, against an exact boundary, in the
    subject, not deleted. A NULL grade, boundary or subject makes the whole
    fragment NULL, which a ``WHERE`` treats as false, as the core does.
    """
    if not _ALIAS.fullmatch(attempt_alias):
        raise ValueError(f"attempt_alias must be a plain SQL alias, got {attempt_alias!r}")
    if not _QUALIFIED_OR_PARAM.fullmatch(subject_operand):
        raise ValueError(
            "subject_operand must be a qualified column (alias.column) or a :bind parameter, "
            f"got {subject_operand!r}"
        )
    a = attempt_alias
    return (
        f"({a}.origin = '{AttemptOrigin.past_paper.value}' AND {a}.deleted_at IS NULL "
        f"AND {a}.boundary_source = '{BoundarySource.exact.value}' "
        f"AND {a}.grade = ANY(CAST(:ladder AS text[])) AND {a}.subject_code = {subject_operand})"
    )


_SUBJECTS_OF_TUTOR: Final = (
    "coalesce((SELECT json_agg(json_build_array(s.code, s.name) ORDER BY s.name, s.code) "
    "FROM tutor_subjects ts JOIN subjects s ON s.code = ts.subject_code "
    "WHERE ts.tutor_profile_id = tp.id), '[]'::json)"
)

_COHORT_SQL: Final = (
    "WITH firsts AS ("  # noqa: S608 - fragments from constants and the shared predicates
    "SELECT b.subject_code, b.student_id, min(b.starts_at) AS first_start "
    "FROM tutor_bookings b "
    "WHERE b.tutor_profile_id = :tutor_id "
    "AND b.subject_code = ANY(CAST(:subjects AS text[])) "
    f"AND {OUTCOME_MEMBERSHIP_SQL} "
    "GROUP BY b.subject_code, b.student_id) "
    "SELECT f.subject_code, f.student_id, f.first_start, "
    "u.email_verified_at, u.created_at AS account_created_at, "
    "coalesce(p.outcome_stats_opt_out, false) AS opted_out, p.outcome_pref_changed_at, "
    f"{student_ever_blocked_tutor_sql('f.student_id', ':tutor_user_id')} AS ever_blocked, "
    f"{student_block_of_tutor_created_at_sql('f.student_id', ':tutor_user_id')} "
    "AS block_created_at, "
    "EXISTS (SELECT 1 FROM tutor_data_grants g "
    "WHERE g.student_id = f.student_id AND g.tutor_profile_id = :tutor_id) AS ever_granted "
    "FROM firsts f "
    "JOIN users u ON u.id = f.student_id "
    "LEFT JOIN student_tutoring_preferences p ON p.user_id = f.student_id "
    "ORDER BY f.subject_code, f.first_start, f.student_id"
)

_OBSERVATIONS_SQL: Final = (
    "SELECT c.ref, a.grade, a.recorded_at "  # noqa: S608 - fragments from constants
    "FROM unnest(CAST(:refs AS integer[]), CAST(:students AS uuid[]), "
    "CAST(:subject_codes AS text[]), CAST(:starts AS timestamptz[])) "
    "AS c(ref, student_id, subject_code, first_start) "
    "JOIN attempts a ON a.user_id = c.student_id "
    f"WHERE {outcome_eligible_attempt_sql('a', 'c.subject_code')} "
    "AND a.recorded_at >= c.first_start - make_interval(secs => :before_secs) "
    "AND a.recorded_at < c.first_start + make_interval(secs => :during_secs) "
    "ORDER BY c.ref, a.recorded_at, a.id"
)


# ---------------------------------------------------------------------------
# Statements 2 and 3 (session-level, so the parity test can drive them)
# ---------------------------------------------------------------------------


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


def _optional_instant(value: object) -> datetime | None:
    return None if value is None else _instant(value)


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _entry(mapping: RowMapping, ref: int, now: datetime) -> CohortEntry:
    start = _instant(mapping["first_start"])
    member = CohortMember(
        ref=ref,
        first_session_start=start,
        eligible=is_member_eligible(
            first_session_start=start,
            email_verified_at=_optional_instant(mapping["email_verified_at"]),
            account_created_at=_instant(mapping["account_created_at"]),
            opted_out=bool(mapping["opted_out"]),
            ever_blocked_tutor=bool(mapping["ever_blocked"]),
        ),
        ever_granted=bool(mapping["ever_granted"]),
        recent_change=is_recent_change(
            now=now,
            outcome_pref_changed_at=_optional_instant(mapping["outcome_pref_changed_at"]),
            block_created_at=_optional_instant(mapping["block_created_at"]),
        ),
    )
    return CohortEntry(
        subject_code=str(mapping["subject_code"]),
        student_id=_as_uuid(mapping["student_id"]),
        member=member,
    )


def cohort_in_session(
    session: Session,
    *,
    tutor_profile_id: uuid.UUID,
    tutor_user_id: uuid.UUID,
    subject_codes: Sequence[str],
    now: datetime,
) -> list[CohortEntry]:
    """Statement 2: every (subject, student) with a counted session with this tutor.

    Eligible or not: an ineligible member's recent change still hides the
    subject's figures. ``now`` must be the transaction's ``now()`` (the
    membership predicate reads it). ``ref`` numbers the rows in
    ``(subject, S, student)`` order, so it is stable, unique across subjects and
    never a user id.
    """
    if not subject_codes:
        return []
    rows = session.execute(
        sa.text(_COHORT_SQL),
        {
            "tutor_id": tutor_profile_id,
            "tutor_user_id": tutor_user_id,
            "subjects": list(subject_codes),
        },
    ).all()
    return [_entry(row._mapping, ref, now) for ref, row in enumerate(rows, start=1)]


def observations_in_session(
    session: Session, entries: Sequence[CohortEntry]
) -> list[GradeObservation]:
    """Statement 3: the eligible grades of ``entries`` in ``[S - 180 d, S + 120 d)``.

    The core picks the before and during grades out of these; the SQL only
    narrows the read to rows the core could use. No statement runs for no
    entries.
    """
    if not entries:
        return []
    rows = session.execute(
        sa.text(_OBSERVATIONS_SQL),
        {
            "refs": [entry.member.ref for entry in entries],
            "students": [entry.student_id for entry in entries],
            "subject_codes": [entry.subject_code for entry in entries],
            "starts": [entry.member.first_session_start for entry in entries],
            "ladder": list(LADDER),
            "before_secs": BEFORE_LOOKBACK.total_seconds(),
            "during_secs": DURING_WINDOW.total_seconds(),
        },
    ).all()
    return [
        GradeObservation(
            ref=int(row._mapping["ref"]),
            grade=str(row._mapping["grade"]),
            recorded_at=_instant(row._mapping["recorded_at"]),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Statement 1 and the whole read
# ---------------------------------------------------------------------------


def _subjects(raw: object) -> tuple[SubjectRef, ...]:
    if not isinstance(raw, list):
        raise TypeError(f"subject aggregate is not a list: {raw!r}")
    refs: list[SubjectRef] = []
    for item in raw:
        if not (
            isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)
        ):
            raise TypeError(f"subject entry is not a code and a name: {item!r}")
        refs.append(SubjectRef(code=item[0], name=item[1]))
    return tuple(refs)


def _profile_check(
    session: Session, *, where: str, params: Mapping[str, object]
) -> _ProfileCheck | None:
    """Statement 1. ``where`` is a trusted fragment over ``tutor_profiles tp`` built here."""
    row = session.execute(
        sa.text(
            "SELECT tp.id, tp.user_id, now() AS db_now, "  # noqa: S608 - trusted fragments
            f"{_SUBJECTS_OF_TUTOR} AS subjects FROM tutor_profiles tp WHERE {where}"
        ),
        dict(params),
    ).first()
    if row is None:
        return None
    mapping = row._mapping
    return _ProfileCheck(
        tutor_id=_as_uuid(mapping["id"]),
        tutor_user_id=_as_uuid(mapping["user_id"]),
        db_now=_instant(mapping["db_now"]),
        subjects=_subjects(mapping["subjects"]),
    )


def _figures(session: Session, check: _ProfileCheck) -> TutorOutcomes:
    """Statements 2 and 3, then the core, subject by subject."""
    now = check.db_now
    entries = cohort_in_session(
        session,
        tutor_profile_id=check.tutor_id,
        tutor_user_id=check.tutor_user_id,
        subject_codes=[subject.code for subject in check.subjects],
        now=now,
    )
    members: dict[str, list[CohortMember]] = {subject.code: [] for subject in check.subjects}
    for entry in entries:
        members[entry.subject_code].append(entry.member)
    # Only grades the figures will use are read: the published members of each
    # subject the hold does not hide (outcome_for_subject reads no other).
    readable: set[int] = set()
    for subject_members in members.values():
        if not any(member.recent_change for member in subject_members):
            published = published_members(subject_members, now=now, k=OUTCOME_K_MIN)
            readable.update(member.ref for member in published)
    observations = observations_in_session(
        session, [entry for entry in entries if entry.member.ref in readable]
    )
    figures = tuple(
        SubjectFigures(
            subject=subject,
            outcome=outcome_for_subject(
                members[subject.code], observations, now=now, ladder=LADDER, k=OUTCOME_K_MIN
            ),
        )
        for subject in check.subjects
    )
    return TutorOutcomes(tutor_id=check.tutor_id, ladder=LADDER, subjects=figures)


class TutorOutcomesRepository:
    """Outcome reads over a ``sessionmaker``; one read transaction per call, nothing cached."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    def outcomes_for_viewer(
        self, tutor_profile_id: uuid.UUID, viewer_id: uuid.UUID, viewer_role: Role | str
    ) -> TutorOutcomes | None:
        """SP4: the figures, or ``None`` when the tutor is hidden from the caller (O11).

        Hidden means what it means for SP2: not listed, paused, unknown, or (for a
        student; parents hold no blocks) an active block in either direction.
        """
        where = f"tp.id = :tutor_id AND {listed_and_not_paused_sql('tp')}"
        params: dict[str, object] = {"tutor_id": tutor_profile_id}
        if Role(viewer_role) is Role.student:
            where += f" AND NOT {active_block_between_sql(':viewer_id', 'tp.user_id')}"
            params["viewer_id"] = viewer_id
        with self._sessionmaker() as session:
            check = _profile_check(session, where=where, params=params)
            return None if check is None else _figures(session, check)

    def preview(self, tutor_profile_id: uuid.UUID) -> TutorPreview | None:
        """T8: the caller's own profile, as SP2 builds it, and the figures in two states.

        ``None`` only for an unknown profile id (profiles are never deleted). The
        profile is read in any listing state; the figures are ``None`` unless the
        profile is ``listed`` (paused or not) or ``pending_review`` (ID-7).
        """
        with self._sessionmaker() as session:
            profile = fetch_profile_view(
                session, where="tp.id = :tutor_id", params={"tutor_id": tutor_profile_id}
            )
            if profile is None:
                return None
            check = _profile_check(
                session,
                where=f"tp.id = :tutor_id AND tp.listing_state IN {_PREVIEW_STATES_SQL}",
                params={"tutor_id": tutor_profile_id},
            )
            outcomes = None if check is None else _figures(session, check)
        return TutorPreview(profile=profile, outcomes=outcomes)


__all__ = [
    "LADDER",
    "CohortEntry",
    "SubjectFigures",
    "TutorOutcomes",
    "TutorOutcomesRepository",
    "TutorPreview",
    "cohort_in_session",
    "observations_in_session",
    "outcome_eligible_attempt_sql",
]
