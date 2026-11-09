"""Persistence for the landing-page waitlist (``waitlist_applicants``).

The public flow is two writes: :meth:`WaitlistRepository.create` (step 1: email, name, role, UTM,
consent; returns the one-time completion token) and :meth:`WaitlistRepository.complete`
(step 2: the rest, redeemed with that token). Only the SHA-256 digest of the token is stored.
The admin side reads and filters the queue, edits status and note, and exports the filtered
set. :meth:`WaitlistRepository.digest_stats` aggregates the last day for the team digest and
never returns an email or a phone number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.waitlist import TOKEN_TTL_HOURS, hash_token, new_completion_token
from lemely.db.models.waitlist import (
    WaitlistApplicant,
    WaitlistDigestLog,
    WaitlistRole,
    WaitlistStatus,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

SORT_COLUMNS: Final = ("created_at", "email", "name", "role", "status", "exam_session")
PARTIAL: Final = "partial"
UTM_FIELDS: Final = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
_TOP_SUBJECTS: Final = 5
#: A claim with no ``window_end`` older than this is taken as abandoned and may be taken over.
PENDING_CLAIM_LEASE: Final = timedelta(minutes=5)
DigestClaim = Literal["claimed", "sent", "pending"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class WaitlistFilters:
    """The admin queue's filter set. ``status`` is a status value or ``"partial"``."""

    role: str | None = None
    level: str | None = None
    subject: str | None = None
    board: str | None = None
    session: str | None = None
    status: str | None = None
    email_confirmed: bool | None = None
    created_from: date | None = None
    created_to: date | None = None
    q: str | None = None


@dataclass(frozen=True, slots=True)
class CompletionDetails:
    """Step-2 fields, already validated by the DTO."""

    levels: list[str]
    subjects: list[str]
    other_subjects: list[str]
    exam_boards: list[str]
    exam_session: str | None
    phone: str | None
    phone_has_whatsapp: bool
    centre_name: str | None


@dataclass(frozen=True, slots=True)
class DigestStats:
    """The last day's applicants, aggregated. Carries no email, phone or name."""

    total: int
    completed: int
    partial: int
    by_role: dict[str, int] = field(default_factory=dict)
    top_subjects: list[tuple[str, int]] = field(default_factory=list)
    by_board: dict[str, int] = field(default_factory=dict)


def _conditions(
    filters: WaitlistFilters, *, with_status: bool = True
) -> list[sa.ColumnElement[bool]]:
    model = WaitlistApplicant
    out: list[sa.ColumnElement[bool]] = []
    if filters.role is not None:
        out.append(model.role == WaitlistRole(filters.role))
    if filters.level is not None:
        out.append(sa.literal(filters.level) == sa.any_(model.levels))
    if filters.subject == "other":
        out.append(sa.func.cardinality(model.other_subjects) > 0)
    elif filters.subject is not None:
        out.append(sa.literal(filters.subject) == sa.any_(model.subjects))
    if filters.board is not None:
        out.append(sa.literal(filters.board) == sa.any_(model.exam_boards))
    if filters.session is not None:
        out.append(model.exam_session == filters.session)
    if with_status and filters.status is not None:
        if filters.status == PARTIAL:
            out.append(model.completed_at.is_(None))
        else:
            out.append(model.status == WaitlistStatus(filters.status))
    if filters.email_confirmed is not None:
        out.append(model.email_confirmed.is_(filters.email_confirmed))
    if filters.created_from is not None:
        out.append(model.created_at >= datetime.combine(filters.created_from, time.min, UTC))
    if filters.created_to is not None:
        out.append(
            model.created_at
            < datetime.combine(filters.created_to + timedelta(days=1), time.min, UTC)
        )
    if filters.q:
        needle = filters.q.strip().lower()
        out.append(
            sa.or_(
                model.email.icontains(needle, autoescape=True),
                model.name.icontains(needle, autoescape=True),
            )
        )
    return out


class WaitlistRepository:
    """Reads and writes ``waitlist_applicants`` through short, self-committing transactions."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._now = now

    # -- public flow ---------------------------------------------------------------

    def create(
        self,
        *,
        email: str,
        name: str,
        role: str,
        consent_version: str,
        consent_text: str,
        utm: Mapping[str, str | None],
    ) -> str | None:
        """Insert a partial applicant; return its completion token, or ``None`` if listed.

        One ``INSERT .. ON CONFLICT DO NOTHING``: race-safe, and a duplicate takes the same
        single statement as a new row, so the two outcomes cost the same. A duplicate leaves
        the existing row untouched.
        """
        token, digest = new_completion_token()
        moment = self._now()
        values: dict[str, object] = {
            "email": email,
            "name": name,
            "role": WaitlistRole(role),
            "consent_version": consent_version,
            "consent_text": consent_text,
            "consent_at": moment,
            "completion_token_hash": digest,
            "completion_token_expires_at": moment + timedelta(hours=TOKEN_TTL_HOURS),
            **{name: utm.get(name) for name in UTM_FIELDS},
        }
        stmt = (
            pg_insert(WaitlistApplicant)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["email"])
            .returning(WaitlistApplicant.id)
        )
        with self._sessionmaker.begin() as session:
            inserted = session.execute(stmt).scalar_one_or_none()
        return token if inserted is not None else None

    def complete(self, token: str, details: CompletionDetails) -> bool:
        """Redeem ``token`` and fill in step 2; ``False`` when it is unknown, expired or used.

        The row is locked, so two concurrent redemptions cannot both succeed. Centre name is
        kept only for a centre administrator; exam session only for everyone else.
        """
        with self._sessionmaker.begin() as session:
            row = session.execute(
                sa.select(WaitlistApplicant)
                .where(
                    WaitlistApplicant.completion_token_hash == hash_token(token),
                    WaitlistApplicant.completion_token_expires_at > self._now(),
                    WaitlistApplicant.completed_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                return False
            is_centre = row.role is WaitlistRole.centre_admin
            row.levels = details.levels
            row.subjects = details.subjects
            row.other_subjects = details.other_subjects
            row.exam_boards = details.exam_boards
            row.exam_session = None if is_centre else details.exam_session
            row.phone = details.phone
            row.phone_has_whatsapp = details.phone_has_whatsapp if details.phone else False
            row.centre_name = details.centre_name if is_centre else None
            row.completion_token_hash = None
            row.completion_token_expires_at = None
            row.completed_at = self._now()
        return True

    # -- admin ---------------------------------------------------------------------

    def get(self, applicant_id: uuid.UUID) -> WaitlistApplicant | None:
        with self._sessionmaker() as session:
            return session.get(WaitlistApplicant, applicant_id)

    def update(
        self,
        applicant_id: uuid.UUID,
        *,
        status: str | None,
        admin_note: str | None,
        set_note: bool,
    ) -> WaitlistApplicant | None:
        """Change status and/or note; ``None`` when the applicant does not exist."""
        with self._sessionmaker.begin() as session:
            row = session.get(WaitlistApplicant, applicant_id, with_for_update=True)
            if row is None:
                return None
            if status is not None:
                row.status = WaitlistStatus(status)
            if set_note:
                row.admin_note = admin_note
            session.flush()
            session.refresh(row)  # ``updated_at`` is set by the database on UPDATE
            return row

    def list_page(
        self,
        filters: WaitlistFilters,
        *,
        sort: str = "created_at",
        descending: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WaitlistApplicant], int]:
        """One page of the filtered queue and the total matching the filters."""
        where = _conditions(filters)
        with self._sessionmaker() as session:
            total = session.execute(
                sa.select(sa.func.count()).select_from(WaitlistApplicant).where(*where)
            ).scalar_one()
            rows = (
                session.execute(
                    sa.select(WaitlistApplicant)
                    .where(*where)
                    .order_by(*self._order(sort, descending))
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
                .scalars()
                .all()
            )
        return list(rows), total

    def export_rows(
        self, filters: WaitlistFilters, *, sort: str = "created_at", descending: bool = True
    ) -> Sequence[WaitlistApplicant]:
        """Every applicant matching ``filters`` (no paging), for the CSV export."""
        with self._sessionmaker() as session:
            return (
                session.execute(
                    sa.select(WaitlistApplicant)
                    .where(*_conditions(filters))
                    .order_by(*self._order(sort, descending))
                )
                .scalars()
                .all()
            )

    def counts(self, filters: WaitlistFilters) -> dict[str, int]:
        """Status counts over the filtered set, ignoring the status filter itself.

        ``partial`` overlaps the statuses (a partial applicant is also ``new``); ``all`` is
        the whole filtered set.
        """
        model = WaitlistApplicant
        where = _conditions(filters, with_status=False)
        with self._sessionmaker() as session:
            by_status = {
                status: n
                for status, n in session.execute(
                    sa.select(model.status, sa.func.count()).where(*where).group_by(model.status)
                ).all()
            }
            partial = session.execute(
                sa.select(sa.func.count()).where(*where, model.completed_at.is_(None))
            ).scalar_one()
        out = {s.value: by_status.get(s, 0) for s in WaitlistStatus}
        out[PARTIAL] = partial
        out["all"] = sum(out[s.value] for s in WaitlistStatus)
        return out

    @staticmethod
    def _order(
        sort: str, descending: bool
    ) -> tuple[sa.UnaryExpression[object], sa.UnaryExpression[uuid.UUID]]:
        column: sa.ColumnElement[object] = getattr(
            WaitlistApplicant, sort if sort in SORT_COLUMNS else "created_at"
        )
        primary = column.desc() if descending else column.asc()
        if sort == "name":
            primary = primary.nulls_last()
        return primary, WaitlistApplicant.id.asc()

    # -- digest --------------------------------------------------------------------

    def digest_stats(self, since: datetime, until: datetime) -> DigestStats:
        """Aggregate applicants created in ``[since, until)``. No personal data leaves here."""
        model = WaitlistApplicant
        with self._sessionmaker() as session:
            rows = session.execute(
                sa.select(
                    model.role,
                    model.subjects,
                    model.other_subjects,
                    model.exam_boards,
                    model.completed_at,
                ).where(model.created_at >= since, model.created_at < until)
            ).all()
        by_role: Counter[str] = Counter()
        subjects: Counter[str] = Counter()
        boards: Counter[str] = Counter()
        completed = 0
        for role, row_subjects, row_other, row_boards, completed_at in rows:
            by_role[role.value] += 1
            subjects.update(row_subjects)
            if row_other:  # free text counts once, as "Other"
                subjects["other"] += 1
            boards.update(row_boards)
            completed += completed_at is not None
        return DigestStats(
            total=len(rows),
            completed=completed,
            partial=len(rows) - completed,
            by_role=dict(by_role),
            top_subjects=subjects.most_common(_TOP_SUBJECTS),
            by_board=dict(boards),
        )

    def db_now(self) -> datetime:
        """The database's clock (UTC), the one ``created_at`` is stamped with."""
        with self._sessionmaker() as session:
            return session.execute(sa.select(sa.func.now())).scalar_one()

    def last_digest_window_end(self) -> datetime | None:
        """Where the most recent *sent* digest's window stopped, or ``None`` if none was."""
        with self._sessionmaker() as session:
            return session.execute(
                sa.select(sa.func.max(WaitlistDigestLog.window_end))
            ).scalar_one()

    def claim_digest_day(self, day: date, new_applicants: int) -> DigestClaim:
        """Try to claim ``day`` for the digest (one per UTC day).

        * ``"claimed"``: this call owns the day and should send. That is a fresh claim, or the
          takeover of a *stale* pending one (a claim whose send never finished and whose cursor
          was never set, older than :data:`PENDING_CLAIM_LEASE`).
        * ``"sent"``: the digest for ``day`` went out (its ``window_end`` is set).
        * ``"pending"``: another call claimed the day recently and has not finished (or just
          failed and could not release): not sent, and not ours to take over yet.

        The claim carries no ``window_end``: the cursor only moves in :meth:`mark_digest_sent`.
        """
        insert = pg_insert(WaitlistDigestLog).values(day=day, new_applicants=new_applicants)
        stmt = insert.on_conflict_do_update(
            index_elements=["day"],
            set_={"sent_at": sa.func.now(), "new_applicants": insert.excluded.new_applicants},
            where=sa.and_(
                WaitlistDigestLog.window_end.is_(None),
                WaitlistDigestLog.sent_at < sa.func.now() - PENDING_CLAIM_LEASE,
            ),
        ).returning(WaitlistDigestLog.day)
        with self._sessionmaker.begin() as session:
            if session.execute(stmt).scalar_one_or_none() is not None:
                return "claimed"
            window_end = session.execute(
                sa.select(WaitlistDigestLog.window_end).where(WaitlistDigestLog.day == day)
            ).scalar_one_or_none()
        return "sent" if window_end is not None else "pending"

    def mark_digest_sent(self, day: date, window_end: datetime) -> None:
        """Advance the cursor: the digest for ``day`` went out and covered up to ``window_end``."""
        with self._sessionmaker.begin() as session:
            session.execute(
                sa.update(WaitlistDigestLog)
                .where(WaitlistDigestLog.day == day)
                .values(window_end=window_end)
            )

    def release_digest_day(self, day: date) -> None:
        """Give ``day`` back after a failed send so the scheduler's retry can send it."""
        with self._sessionmaker.begin() as session:
            session.execute(sa.delete(WaitlistDigestLog).where(WaitlistDigestLog.day == day))
