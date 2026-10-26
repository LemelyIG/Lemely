"""The tutor directory: public and logged-in lists, the public card, the logged-in profile.

SPEC ``docs/tutoring/SPEC.md`` §b.2 P1, P2, SP1, SP2 and §e.3. Read-only.

**Visibility comes from the shared predicates, never restated here** (PLAN §1.4
#9, O11): a tutor is in the directory when
:func:`~lemely.db.tutoring_predicates.listed_and_not_paused_sql` holds, and a
student never sees a tutor with whom an active block exists in either direction
(:func:`~lemely.db.tutoring_predicates.active_block_between_sql`, keyed on
``users.id``, so the tutor side is ``tutor_profiles.user_id``). Parents hold no
blocks (SPEC §b.2 SP1), so the anti-join applies to student viewers only. The
public card (P2) and the profile (SP2) use the same predicate, so every hidden
state answers the same "not found" (PP-6).

**Order and keyset (F10).** ``rank_score DESC, first_listed_at ASC NULLS LAST,
id ASC``, the order of ``ix_tutor_profiles_directory``. ``first_listed_at`` is
NULL for a profile that reached ``listed`` without a first approval (a
reinstatement after a suspension from review: SPEC §a.3 reinstates "restoring
nothing"), so the cursor carries an explicit "missing" flag rather than a NULL
the typed codec cannot express. The cursor is
``(rank_score, first_listed_at_missing, first_listed_at, id)``, typed by
:mod:`lemely.core.keyset` and tagged with its endpoint (O21).

**minRating (SPEC §i.4).** "New" tutors (fewer than
``core.tutor_ratings.NEW_THRESHOLD`` distinct students) never match, and the
comparison is against the one-decimal average the card shows (half up, as
``core.tutor_ratings.rating_display`` rounds), not the stored two-decimal
``rating_avg``: a tutor whose card says "4.5" always matches ``minRating=4.5``.

**Availability (SP1).** :func:`availability_match_sql` is the SQL twin of
``core.tutor_directory.rule_matches`` (parity-tested, F6): an empty day set or
time set means no filter on that dimension, and windows overlap half-open.

**Query budget (SPEC §e.3, F24).** A first page is three statements (profiles,
with the block anti-join for students; subjects of the page; facets), a later
page two, the public card and the profile two each, whatever the row count.

Every value reaches SQL as a bound parameter; the only text spliced into a
statement is a fragment built here or in ``tutoring_predicates`` from constants.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa

from lemely.core.booking import AvailabilityRule
from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.tutor_directory import TIME_OF_DAY_MINUTES
from lemely.core.tutor_ratings import NEW_THRESHOLD
from lemely.db.models.enums import Role
from lemely.db.tutoring_predicates import active_block_between_sql, listed_and_not_paused_sql

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.tutor_directory import TimeOfDay

Mode = Literal["virtual", "in_person", "other"]

#: Card order of the modes, and the ``tutor_profiles`` flag behind each.
MODES: Final[tuple[Mode, ...]] = ("virtual", "in_person", "other")
_MODE_COLUMN: Final[Mapping[str, str]] = {
    "virtual": "offers_virtual",
    "in_person": "offers_in_person",
    "other": "offers_other",
}

#: SPEC §0 "Paging": ``limit`` 1..50.
MAX_PAGE_SIZE: Final = 50

_ALIAS: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PARAM: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: The value a cursor carries in the instant slot when ``first_listed_at`` is NULL.
#: Never compared: the "missing" flag beside it decides.
_NO_INSTANT: Final = datetime(1970, 1, 1, tzinfo=UTC)
_CURSOR_TYPES: Final = (Decimal, bool, datetime, uuid.UUID)

_CARD_COLUMNS: Final = (
    "tp.id, tp.public_first_name, tp.public_last_initial, tp.headline, "
    "tp.offers_virtual, tp.offers_in_person, tp.offers_other, tp.area_code, "
    "tp.rating_sum, tp.rating_count"
)
_ORDER: Final = "tp.rank_score DESC, tp.first_listed_at ASC NULLS LAST, tp.id ASC"


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """A subject by code and display name."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class TutorCard:
    """The public card's inputs (row 5b): nothing a public visitor may not see.

    ``tutor_id`` is ``tutor_profiles.id``, never a ``users.id`` (SC-19).
    """

    tutor_id: uuid.UUID
    public_first_name: str
    public_last_initial: str | None
    headline: str
    subjects: tuple[SubjectRef, ...]
    modes: tuple[Mode, ...]
    area_code: str
    rating_sum: int
    rating_count: int


@dataclass(frozen=True, slots=True)
class PublicCard:
    """P2: the card plus ``indexable`` (row 17), read by the edge worker."""

    card: TutorCard
    indexable: bool


@dataclass(frozen=True, slots=True)
class TutorProfileView:
    """SP2 (and the tutor's own T1): the card plus the logged-in-only fields."""

    card: TutorCard
    bio: str
    qualification_note: str | None
    other_mode_note: str | None
    documents_seen: bool
    availability: tuple[AvailabilityRule, ...]
    zone: str
    first_listed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    """Directory filters. Empty sets and ``None`` mean "not filtered".

    ``days`` and ``times`` exist on SP1 only: the public list has no
    availability filter (row 5b), and :meth:`TutorDirectoryRepository.list_public`
    refuses them.
    """

    subject: str | None = None
    modes: frozenset[str] = frozenset()
    area: str | None = None
    min_rating: Decimal | None = None
    days: frozenset[int] = frozenset()
    times: frozenset[TimeOfDay] = frozenset()


@dataclass(frozen=True, slots=True)
class DirectoryKey:
    """The sort key of the last row of a page: where the next page starts."""

    rank_score: Decimal
    first_listed_at: datetime | None
    tutor_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Facets:
    """Filter options: subjects and area codes of every tutor in the directory."""

    subjects: tuple[SubjectRef, ...]
    area_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DirectoryPage:
    """One keyset page; ``facets`` on the first page only."""

    items: tuple[TutorCard, ...]
    next_key: DirectoryKey | None
    facets: Facets | None


# ---------------------------------------------------------------------------
# Cursor codec (O21)
# ---------------------------------------------------------------------------


def directory_cursor(endpoint: str, key: DirectoryKey) -> str:
    """Encode ``key`` as an opaque cursor tagged with ``endpoint``."""
    missing = key.first_listed_at is None
    return encode_cursor(
        endpoint,
        [key.rank_score, missing, key.first_listed_at or _NO_INSTANT, key.tutor_id],
    )


def parse_directory_cursor(token: str, endpoint: str) -> DirectoryKey:
    """Decode a cursor minted by :func:`directory_cursor` for ``endpoint``.

    Raises :class:`~lemely.core.keyset.CursorError` for anything else: another
    endpoint's tag, the wrong arity, a value of the wrong type.
    """
    rank, missing, instant, tutor_id = decode_cursor(token, endpoint=endpoint, types=_CURSOR_TYPES)
    if not (
        isinstance(rank, Decimal)
        and isinstance(missing, bool)
        and isinstance(instant, datetime)
        and isinstance(tutor_id, uuid.UUID)
    ):  # pragma: no cover - decode_cursor already returns these types
        raise CursorError("cursor has the wrong shape")
    return DirectoryKey(
        rank_score=rank, first_listed_at=None if missing else instant, tutor_id=tutor_id
    )


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------


def _alias(value: str) -> str:
    if _ALIAS.fullmatch(value) is None:
        raise ValueError(f"not a plain SQL alias: {value!r}")
    return value


def availability_match_sql(
    rule_alias: str, days: frozenset[int], times: frozenset[TimeOfDay]
) -> tuple[str, dict[str, object]]:
    """The SQL twin of ``core.tutor_directory.rule_matches`` for one rule row.

    ``rule_alias`` names a row with ``iso_weekday``, ``start_minute`` and
    ``end_minute``. Returns the fragment and its bind parameters. With both sets
    empty the fragment is ``TRUE``, exactly as ``rule_matches`` is.
    """
    a = _alias(rule_alias)
    parts: list[str] = []
    params: dict[str, object] = {}
    if days:
        if not all(1 <= day <= 7 for day in days):
            raise ValueError(f"ISO weekdays are 1 to 7, got {sorted(days)}")
        parts.append(f"{a}.iso_weekday = ANY(CAST(:avail_days AS integer[]))")
        params["avail_days"] = sorted(days)
    if times:
        unknown = set(times) - set(TIME_OF_DAY_MINUTES)
        if unknown:
            raise ValueError(f"unknown time-of-day buckets: {sorted(unknown)}")
        overlaps: list[str] = []
        # Parameter names come from the module's own bucket names, never the caller.
        for bucket, (start, end) in TIME_OF_DAY_MINUTES.items():
            if bucket in times:
                overlaps.append(
                    f"({a}.start_minute < :avail_{bucket}_end "
                    f"AND :avail_{bucket}_start < {a}.end_minute)"
                )
                params[f"avail_{bucket}_start"] = start
                params[f"avail_{bucket}_end"] = end
        parts.append("(" + " OR ".join(overlaps) + ")")
    if not parts:
        return "TRUE", params
    return "(" + " AND ".join(parts) + ")", params


def min_rating_sql(profile_alias: str, param: str = "min_rating") -> str:
    """``minRating`` for a ``tutor_profiles`` row (SPEC §b.2 P1 as decided in §i.4).

    Rated (at least ``NEW_THRESHOLD`` distinct students) and the one-decimal
    average, rounded half up as the card rounds it, at least ``:param``.
    ``NULLIF`` keeps a zero count from dividing whatever order Postgres
    evaluates the conjuncts in.
    """
    a = _alias(profile_alias)
    if _PARAM.fullmatch(param) is None:
        raise ValueError(f"not a bind parameter name: {param!r}")
    return (
        f"({a}.rating_count >= {NEW_THRESHOLD} AND "
        f"round({a}.rating_sum::numeric / NULLIF({a}.rating_count, 0), 1) >= :{param})"
    )


def _after_sql(key: DirectoryKey) -> tuple[str, dict[str, object]]:
    """Rows strictly after ``key`` in :data:`_ORDER` (NULL ``first_listed_at`` sorts last)."""
    params: dict[str, object] = {"k_rank": key.rank_score, "k_id": key.tutor_id}
    if key.first_listed_at is None:
        tie = "(tp.first_listed_at IS NULL AND tp.id > :k_id)"
    else:
        tie = (
            "(tp.first_listed_at IS NULL OR tp.first_listed_at > :k_first "
            "OR (tp.first_listed_at = :k_first AND tp.id > :k_id))"
        )
        params["k_first"] = key.first_listed_at
    return f"(tp.rank_score < :k_rank OR (tp.rank_score = :k_rank AND {tie}))", params


def _filter_sql(filters: DirectoryFilters) -> tuple[list[str], dict[str, object]]:
    where: list[str] = []
    params: dict[str, object] = {}
    if filters.subject is not None:
        where.append(
            "EXISTS (SELECT 1 FROM tutor_subjects ts "
            "WHERE ts.tutor_profile_id = tp.id AND ts.subject_code = :subject)"
        )
        params["subject"] = filters.subject
    if filters.modes:
        unknown = set(filters.modes) - set(_MODE_COLUMN)
        if unknown:
            raise ValueError(f"unknown tutoring modes: {sorted(unknown)}")
        flags = [f"tp.{_MODE_COLUMN[mode]}" for mode in MODES if mode in filters.modes]
        where.append("(" + " OR ".join(flags) + ")")
    if filters.area is not None:
        where.append("tp.area_code = :area")
        params["area"] = filters.area
    if filters.min_rating is not None:
        where.append(min_rating_sql("tp"))
        params["min_rating"] = filters.min_rating
    if filters.days or filters.times:
        fragment, extra = availability_match_sql("r", filters.days, filters.times)
        where.append(
            "EXISTS (SELECT 1 FROM tutor_availability_rules r "  # noqa: S608 - fragment built above
            f"WHERE r.tutor_profile_id = tp.id AND {fragment})"
        )
        params.update(extra)
    return where, params


# ---------------------------------------------------------------------------
# Row mapping and shared reads
# ---------------------------------------------------------------------------


def subjects_by_tutor(
    session: Session, tutor_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[SubjectRef, ...]]:
    """The subjects of each tutor in ``tutor_ids``, ordered by name: one statement."""
    if not tutor_ids:
        return {}
    rows = session.execute(
        sa.text(
            "SELECT ts.tutor_profile_id, s.code, s.name FROM tutor_subjects ts "
            "JOIN subjects s ON s.code = ts.subject_code "
            "WHERE ts.tutor_profile_id = ANY(CAST(:ids AS uuid[])) "
            "ORDER BY ts.tutor_profile_id, s.name, s.code"
        ),
        {"ids": list(tutor_ids)},
    ).all()
    found: dict[uuid.UUID, list[SubjectRef]] = {}
    for tutor_id, code, name in rows:
        found.setdefault(tutor_id, []).append(SubjectRef(code=code, name=name))
    return {tutor_id: tuple(subjects) for tutor_id, subjects in found.items()}


def _card(row: Row[tuple[object, ...]], subjects: tuple[SubjectRef, ...]) -> TutorCard:
    mapping = row._mapping
    modes: list[Mode] = [mode for mode in MODES if mapping[_MODE_COLUMN[mode]]]
    return TutorCard(
        tutor_id=_as_uuid(mapping["id"]),
        public_first_name=str(mapping["public_first_name"]),
        public_last_initial=_optional_str(mapping["public_last_initial"]),
        headline=str(mapping["headline"]),
        subjects=subjects,
        modes=tuple(modes),
        area_code=str(mapping["area_code"]),
        rating_sum=int(mapping["rating_sum"]),
        rating_count=int(mapping["rating_count"]),
    )


def fetch_profile_view(
    session: Session, *, where: str, params: Mapping[str, object]
) -> TutorProfileView | None:
    """Load one profile view in two statements (SPEC §e.3: profile, then subjects).

    ``where`` is a trusted fragment over ``tutor_profiles tp`` written by a
    repository, never caller text; values go in ``params``. Availability is
    aggregated inside the first statement.
    """
    row = session.execute(
        sa.text(
            f"SELECT {_CARD_COLUMNS}, tp.bio, tp.qualification_note, "  # noqa: S608 - trusted fragments
            "tp.other_mode_note, tp.documents_seen_at IS NOT NULL AS documents_seen, "
            "tp.zone, tp.first_listed_at, "
            "(SELECT coalesce(json_agg(json_build_array(r.iso_weekday, r.start_minute, "
            "r.end_minute) ORDER BY r.iso_weekday, r.start_minute), '[]'::json) "
            "FROM tutor_availability_rules r WHERE r.tutor_profile_id = tp.id) AS availability "
            f"FROM tutor_profiles tp WHERE {where}"
        ),
        dict(params),
    ).first()
    if row is None:
        return None
    mapping = row._mapping
    tutor_id = _as_uuid(mapping["id"])
    subjects = subjects_by_tutor(session, [tutor_id]).get(tutor_id, ())
    return TutorProfileView(
        card=_card(row, subjects),
        bio=str(mapping["bio"]),
        qualification_note=_optional_str(mapping["qualification_note"]),
        other_mode_note=_optional_str(mapping["other_mode_note"]),
        documents_seen=bool(mapping["documents_seen"]),
        availability=_rules(mapping["availability"]),
        zone=str(mapping["zone"]),
        first_listed_at=_optional_instant(mapping["first_listed_at"]),
    )


def _rules(raw: object) -> tuple[AvailabilityRule, ...]:
    if not isinstance(raw, list):
        raise TypeError(f"availability aggregate is not a list: {raw!r}")
    rules: list[AvailabilityRule] = []
    for item in raw:
        if not (
            isinstance(item, list) and len(item) == 3 and all(isinstance(v, int) for v in item)
        ):
            raise TypeError(f"availability entry is not three integers: {item!r}")
        rules.append(
            AvailabilityRule(iso_weekday=item[0], start_minute=item[1], end_minute=item[2])
        )
    return tuple(rules)


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_instant(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TutorDirectoryRepository:
    """Directory reads over a ``sessionmaker``; one short read transaction per call."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    def list_public(
        self, filters: DirectoryFilters, *, after: DirectoryKey | None, limit: int
    ) -> DirectoryPage:
        """P1: one page of the public directory.

        Raises ``ValueError`` for an availability filter (row 5b: the public
        directory has none) or a ``limit`` outside 1..50.
        """
        if filters.days or filters.times:
            raise ValueError("the public directory has no availability filter (row 5b)")
        return self._list(filters, after=after, limit=limit, blocked_for=None)

    def list_for_viewer(
        self,
        viewer_id: uuid.UUID,
        viewer_role: Role | str,
        filters: DirectoryFilters,
        *,
        after: DirectoryKey | None,
        limit: int,
    ) -> DirectoryPage:
        """SP1: one page of the logged-in directory for a student or a parent.

        A student never sees a tutor with whom an active block exists in either
        direction; a parent holds no blocks.
        """
        blocked_for = viewer_id if Role(viewer_role) is Role.student else None
        return self._list(filters, after=after, limit=limit, blocked_for=blocked_for)

    def public_card(self, tutor_id: uuid.UUID) -> PublicCard | None:
        """P2: the card of a listed, unpaused tutor, else ``None`` (two statements)."""
        with self._sessionmaker() as session:
            row = session.execute(
                sa.text(
                    f"SELECT {_CARD_COLUMNS}, tp.indexable FROM tutor_profiles tp "  # noqa: S608 - constants
                    f"WHERE tp.id = :tutor_id AND {listed_and_not_paused_sql('tp')}"
                ),
                {"tutor_id": tutor_id},
            ).first()
            if row is None:
                return None
            subjects = subjects_by_tutor(session, [tutor_id]).get(tutor_id, ())
            return PublicCard(card=_card(row, subjects), indexable=bool(row._mapping["indexable"]))

    def profile_for_viewer(
        self, tutor_id: uuid.UUID, viewer_id: uuid.UUID, viewer_role: Role | str
    ) -> TutorProfileView | None:
        """SP2: the logged-in profile, ``None`` unless listed, unpaused and unblocked."""
        where = f"tp.id = :tutor_id AND {listed_and_not_paused_sql('tp')}"
        params: dict[str, object] = {"tutor_id": tutor_id}
        if Role(viewer_role) is Role.student:
            where += f" AND NOT {active_block_between_sql(':viewer_id', 'tp.user_id')}"
            params["viewer_id"] = viewer_id
        with self._sessionmaker() as session:
            return fetch_profile_view(session, where=where, params=params)

    def facets(self) -> Facets:
        """Subjects and areas of every tutor in the directory (one statement)."""
        with self._sessionmaker() as session:
            return self._facets(session)

    # -- internals ----------------------------------------------------------

    def _list(
        self,
        filters: DirectoryFilters,
        *,
        after: DirectoryKey | None,
        limit: int,
        blocked_for: uuid.UUID | None,
    ) -> DirectoryPage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be 1 to {MAX_PAGE_SIZE}, got {limit}")
        where = [listed_and_not_paused_sql("tp")]
        params: dict[str, object] = {"limit": limit + 1}
        if blocked_for is not None:
            where.append(f"NOT {active_block_between_sql(':viewer_id', 'tp.user_id')}")
            params["viewer_id"] = blocked_for
        filter_where, filter_params = _filter_sql(filters)
        where.extend(filter_where)
        params.update(filter_params)
        if after is not None:
            after_where, after_params = _after_sql(after)
            where.append(after_where)
            params.update(after_params)
        statement = sa.text(
            f"SELECT {_CARD_COLUMNS}, tp.rank_score, tp.first_listed_at "  # noqa: S608 - fragments built here
            f"FROM tutor_profiles tp WHERE {' AND '.join(where)} "
            f"ORDER BY {_ORDER} LIMIT :limit"
        )
        with self._sessionmaker() as session:
            rows = session.execute(statement, params).all()
            page_rows = rows[:limit]
            ids = [_as_uuid(row._mapping["id"]) for row in page_rows]
            subjects = subjects_by_tutor(session, ids)
            facets = self._facets(session) if after is None else None
        items = tuple(
            _card(row, subjects.get(tid, ())) for row, tid in zip(page_rows, ids, strict=True)
        )
        next_key = None
        if len(rows) > limit:
            last = page_rows[-1]._mapping
            rank = last["rank_score"]
            if not isinstance(rank, Decimal):  # pragma: no cover - numeric maps to Decimal
                raise TypeError(f"rank_score is not a Decimal: {rank!r}")
            next_key = DirectoryKey(
                rank_score=rank,
                first_listed_at=_optional_instant(last["first_listed_at"]),
                tutor_id=ids[-1],
            )
        return DirectoryPage(items=items, next_key=next_key, facets=facets)

    @staticmethod
    def _facets(session: Session) -> Facets:
        listed = listed_and_not_paused_sql("tp")
        rows = session.execute(
            sa.text(
                "SELECT 'subject' AS kind, s.code, s.name FROM subjects s "  # noqa: S608 - constants
                "WHERE EXISTS (SELECT 1 FROM tutor_subjects ts "
                "JOIN tutor_profiles tp ON tp.id = ts.tutor_profile_id "
                f"WHERE ts.subject_code = s.code AND {listed}) "
                "UNION ALL "
                "SELECT DISTINCT 'area' AS kind, tp.area_code, CAST(NULL AS varchar) "
                f"FROM tutor_profiles tp WHERE {listed}"
            )
        ).all()
        subjects = sorted(
            (
                SubjectRef(code=str(code), name=str(name))
                for kind, code, name in rows
                if kind == "subject"
            ),
            key=lambda ref: (ref.name, ref.code),
        )
        areas = sorted(str(code) for kind, code, _ in rows if kind == "area")
        return Facets(subjects=tuple(subjects), area_codes=tuple(areas))


__all__ = [
    "MAX_PAGE_SIZE",
    "MODES",
    "DirectoryFilters",
    "DirectoryKey",
    "DirectoryPage",
    "Facets",
    "Mode",
    "PublicCard",
    "SubjectRef",
    "TutorCard",
    "TutorDirectoryRepository",
    "TutorProfileView",
    "availability_match_sql",
    "directory_cursor",
    "fetch_profile_view",
    "min_rating_sql",
    "parse_directory_cursor",
    "subjects_by_tutor",
]
