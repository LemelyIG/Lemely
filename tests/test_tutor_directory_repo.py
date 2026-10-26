"""The tutor directory repository (SPEC §b.2 P1, P2, SP1, SP2; §e.3; §i.4).

DB-backed: one throwaway database per module, built with
``Base.metadata.create_all`` (the tutoring models install ``btree_gist``
themselves), emptied after every test. The seeding helpers here are shared with
the other T06 test modules, which import them.

What these tests pin:

* the keyset order ``rank_score DESC, first_listed_at ASC (NULLS LAST), id ASC``
  across pages, with no row lost or repeated;
* the ``minRating`` rule decided in SPEC §i.4: "New" tutors never match, and the
  filter compares the same one-decimal value the card shows (a 4.45 average
  shows "4.5" and matches ``minRating=4.5``);
* the availability filter's SQL is the twin of ``core.tutor_directory.rule_matches``
  over generated inputs (F6), including the empty-set meaning;
* the block anti-join goes through ``active_block_between_sql`` in both directions;
* the SPEC §e.3 query budget: 3 statements for a first page, 2 for later pages,
  2 for the public card and the logged-in profile, independent of row count.
"""

from __future__ import annotations

import itertools
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.tutor_directory import TIME_OF_DAY_MINUTES, rule_matches
from lemely.core.tutor_ratings import bayesian_score, rating_display
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.academic import Subject
from lemely.db.models.enums import Role, TutorListingState
from lemely.db.models.tutoring import (
    TutorAvailabilityRule,
    TutoringBlock,
    TutorProfile,
    TutorSubject,
)
from lemely.db.models.users import User
from lemely.db.tutor_directory_repo import (
    DirectoryFilters,
    DirectoryKey,
    TutorDirectoryRepository,
    availability_match_sql,
    directory_cursor,
    min_rating_sql,
    parse_directory_cursor,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

import_all_models()

NOW = datetime.now(UTC)
_UNSET = object()


# ---------------------------------------------------------------------------
# Database (shared with the other T06 test modules)
# ---------------------------------------------------------------------------


@contextmanager
def tutoring_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table that references users or subjects."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, subjects CASCADE"))


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@contextmanager
def count_statements(factory: sessionmaker[Session]) -> Iterator[list[str]]:
    """Collect every statement sent to the database inside the block."""
    engine = factory.kw["bind"]
    seen: list[str] = []

    def on_execute(*args: object) -> None:
        seen.append(str(args[2]))

    sa.event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        sa.event.remove(engine, "before_cursor_execute", on_execute)


# ---------------------------------------------------------------------------
# Seeding (shared with the other T06 test modules)
# ---------------------------------------------------------------------------


def add_user(
    factory: sessionmaker[Session],
    role: Role | str = Role.student,
    *,
    verified: bool = True,
    display_name: str | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=Role(role),
                display_name=display_name,
                email_verified_at=NOW - timedelta(days=60) if verified else None,
            )
        )
    return uid


def add_subject(
    factory: sessionmaker[Session], code: str | None = None, name: str = "Mathematics"
) -> str:
    code = code or f"S{uuid.uuid4().hex[:7]}"
    with factory.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


@dataclass(frozen=True)
class SeededTutor:
    profile_id: uuid.UUID
    user_id: uuid.UUID


def add_tutor(
    factory: sessionmaker[Session],
    *,
    state: str = "listed",
    paused: bool = False,
    first_name: str = "Sara",
    initial: str | None = "M",
    headline: str = "IGCSE Mathematics, patient and exam focused",
    bio: str = "",
    qualification_note: str | None = None,
    other_mode_note: str | None = None,
    subjects: Sequence[str] = (),
    modes: Sequence[str] = ("virtual",),
    area: str = "cairo",
    rating: tuple[int, int] = (0, 0),
    rank: Decimal | None = None,
    first_listed_at: object = _UNSET,
    indexable: bool = True,
    rules: Sequence[tuple[int, int, int]] = ((4, 1020, 1200),),
    verified: bool = True,
    documents_seen: bool = False,
) -> SeededTutor:
    user_id = add_user(factory, Role.teacher, verified=verified)
    profile_id = uuid.uuid4()
    if first_listed_at is _UNSET:
        first_listed_at = NOW - timedelta(days=30) if state == "listed" else None
    with factory.begin() as session:
        session.add(
            TutorProfile(
                id=profile_id,
                user_id=user_id,
                public_first_name=first_name,
                public_last_initial=initial,
                headline=headline,
                bio=bio,
                qualification_note=qualification_note,
                offers_virtual="virtual" in modes,
                offers_in_person="in_person" in modes,
                offers_other="other" in modes,
                other_mode_note=other_mode_note,
                area_code=area,
                listing_state=TutorListingState(state),
                paused_at=NOW - timedelta(days=1) if paused else None,
                closed_at=NOW - timedelta(days=1) if state == "closed" else None,
                submitted_at=NOW - timedelta(days=40) if state != "draft" else None,
                first_listed_at=first_listed_at,
                indexable=indexable,
                rating_sum=rating[0],
                rating_count=rating[1],
                rank_score=rank if rank is not None else bayesian_score(*rating),
                documents_seen_at=NOW - timedelta(days=20) if documents_seen else None,
            )
        )
        session.flush()
        for code in subjects:
            session.add(TutorSubject(tutor_profile_id=profile_id, subject_code=code))
        for day, start, end in rules:
            session.add(
                TutorAvailabilityRule(
                    tutor_profile_id=profile_id, iso_weekday=day, start_minute=start, end_minute=end
                )
            )
    return SeededTutor(profile_id=profile_id, user_id=user_id)


def add_block(
    factory: sessionmaker[Session],
    blocker: uuid.UUID,
    blocked: uuid.UUID,
    *,
    removed: bool = False,
) -> None:
    with factory.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=blocker,
                blocked_user_id=blocked,
                removed_at=NOW if removed else None,
            )
        )


def set_block_removed(
    factory: sessionmaker[Session], blocker: uuid.UUID, blocked: uuid.UUID
) -> None:
    with factory.begin() as session:
        row = session.get(TutoringBlock, (blocker, blocked))
        assert row is not None
        row.removed_at = NOW


def _ids(page_items: Sequence[object]) -> list[uuid.UUID]:
    return [item.tutor_id for item in page_items]  # type: ignore[attr-defined]


def _walk_public(
    repo: TutorDirectoryRepository, filters: DirectoryFilters, *, limit: int
) -> tuple[list[uuid.UUID], int]:
    """Every id ``list_public`` returns, following cursors through the codec."""
    collected: list[uuid.UUID] = []
    after: DirectoryKey | None = None
    pages = 0
    while True:
        page = repo.list_public(filters, after=after, limit=limit)
        pages += 1
        collected.extend(_ids(page.items))
        if page.next_key is None:
            return collected, pages
        after = parse_directory_cursor(
            directory_cursor("public_tutors", page.next_key), "public_tutors"
        )
        assert pages < 50, "pagination did not terminate"


# ---------------------------------------------------------------------------
# Order and keyset
# ---------------------------------------------------------------------------


def test_directory_sort_rank_then_first_listed_then_id(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    early, late = NOW - timedelta(days=90), NOW - timedelta(days=10)
    plan = [
        (Decimal("4.800000"), late),
        (Decimal("4.500000"), early),
        (Decimal("4.500000"), late),
        (Decimal("4.500000"), late),
        (Decimal("4.500000"), late),
        # Reinstated after a suspension from review: listed, never first-listed.
        (Decimal("4.500000"), None),
        (Decimal("4.000000"), early),
        (Decimal("4.000000"), None),
        (Decimal("3.900000"), early),
    ]
    seeded = [
        (rank, first, add_tutor(sm, rank=rank, first_listed_at=first).profile_id)
        for rank, first in plan
    ]
    # Never in the directory: one per hidden state, and a paused listing.
    for state in ("draft", "pending_review", "rejected", "suspended", "closed"):
        add_tutor(sm, state=state, rank=Decimal("5.000000"))
    add_tutor(sm, paused=True, rank=Decimal("5.000000"))

    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    expected = [
        pid
        for _, _, pid in sorted(
            seeded, key=lambda row: (-row[0], row[1] is None, row[1] or epoch, row[2])
        )
    ]

    for limit in (1, 2, 4, 50):
        collected, pages = _walk_public(repo, DirectoryFilters(), limit=limit)
        assert collected == expected, limit
        # One page per `limit` rows: a full last page carries no cursor.
        assert pages == -(-len(expected) // limit), limit
    assert len(set(expected)) == len(plan) == 9


def test_directory_cursor_round_trip_keeps_a_missing_first_listed_at() -> None:
    key = DirectoryKey(rank_score=Decimal("4.170000"), first_listed_at=None, tutor_id=uuid.uuid4())
    assert parse_directory_cursor(directory_cursor("tutors", key), "tutors") == key
    stamped = DirectoryKey(
        rank_score=Decimal("4.000000"), first_listed_at=NOW, tutor_id=uuid.uuid4()
    )
    assert parse_directory_cursor(directory_cursor("tutors", stamped), "tutors") == stamped


# ---------------------------------------------------------------------------
# minRating (SPEC §b.2 P1 and §i.4 rating rounding)
# ---------------------------------------------------------------------------


def test_min_rating_excludes_new_tutors(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    new = add_tutor(sm, rating=(10, 2)).profile_id  # 5.0 average, but "New"
    four = add_tutor(sm, rating=(12, 3)).profile_id  # 4.0
    shows_4_5 = add_tutor(sm, rating=(89, 20)).profile_id  # 4.45 -> card "4.5"
    shows_4_4 = add_tutor(sm, rating=(88, 20)).profile_id  # 4.40 -> card "4.4"
    # The card rule the filter must agree with, from core (independent of the repo).
    assert rating_display(89, 20).average == 4.5
    assert rating_display(10, 2).state == "new"

    def matching(min_rating: str | None) -> set[uuid.UUID]:
        filters = DirectoryFilters(min_rating=Decimal(min_rating) if min_rating else None)
        return set(_ids(repo.list_public(filters, after=None, limit=50).items))

    assert matching(None) == {new, four, shows_4_5, shows_4_4}
    assert matching("1.0") == {four, shows_4_5, shows_4_4}
    assert matching("4.0") == {four, shows_4_5, shows_4_4}
    assert matching("4.5") == {shows_4_5}
    assert matching("5.0") == set()


def test_min_rating_filter_matches_card_rounding(sm: sessionmaker[Session]) -> None:
    """The SQL fragment and ``rating_display`` agree on every (sum, count) up to 25 students."""
    rows = [(s, c) for c in range(26) for s in range(c, 5 * c + 1)]
    index = list(range(len(rows)))
    sql = (
        "SELECT tp.i FROM unnest(CAST(:i AS integer[]), CAST(:s AS integer[]), "  # noqa: S608
        f"CAST(:c AS integer[])) AS tp(i, rating_sum, rating_count) WHERE {min_rating_sql('tp')}"
    )
    compared = 0
    with sm() as session:
        for step in range(2, 11):
            minimum = Decimal(step) / 2
            got = set(
                session.execute(
                    sa.text(sql),
                    {
                        "i": index,
                        "s": [s for s, _ in rows],
                        "c": [c for _, c in rows],
                        "min_rating": minimum,
                    },
                ).scalars()
            )
            want = set()
            for i, (s, c) in enumerate(rows):
                shown = rating_display(s, c)
                if shown.state == "rated" and Decimal(str(shown.average)) >= minimum:
                    want.add(i)
            assert got == want, minimum
            compared += len(rows)
    assert compared == 9 * len(rows) > 9 * 1000


# ---------------------------------------------------------------------------
# Availability filter (SP1; SPEC §b.2, §i.4; F6)
# ---------------------------------------------------------------------------

_BOUNDARIES = (0, 345, 360, 375, 705, 720, 735, 1005, 1020, 1035, 1305, 1320, 1335, 1440)


@dataclass(frozen=True)
class _Rule:
    iso_weekday: int
    start_minute: int
    end_minute: int


def test_time_of_day_filter_sql_matches_rule_matches(sm: sessionmaker[Session]) -> None:
    rules = [
        _Rule(day, start, end)
        for day in (1, 4, 7)
        for start, end in itertools.combinations(_BOUNDARIES, 2)
    ]
    day_sets = [
        frozenset(),
        frozenset({1}),
        frozenset({4, 7}),
        frozenset(range(1, 8)),
        frozenset({2}),
    ]
    buckets = tuple(TIME_OF_DAY_MINUTES)
    time_sets = [
        frozenset(combo) for size in range(4) for combo in itertools.combinations(buckets, size)
    ]
    combos = 0
    outcomes: set[bool] = set()
    with sm() as session:
        for days in day_sets:
            for times in time_sets:
                fragment, params = availability_match_sql("r", days, times)
                sql = (
                    "SELECT r.i FROM unnest(CAST(:i AS integer[]), CAST(:d AS integer[]), "  # noqa: S608
                    "CAST(:s AS integer[]), CAST(:e AS integer[])) "
                    f"AS r(i, iso_weekday, start_minute, end_minute) WHERE {fragment}"
                )
                got = set(
                    session.execute(
                        sa.text(sql),
                        {
                            **params,
                            "i": list(range(len(rules))),
                            "d": [r.iso_weekday for r in rules],
                            "s": [r.start_minute for r in rules],
                            "e": [r.end_minute for r in rules],
                        },
                    ).scalars()
                )
                for i, rule in enumerate(rules):
                    expected = rule_matches(rule, days, times)
                    outcomes.add(expected)
                    assert (i in got) == expected, (rule, sorted(days), sorted(times))
                combos += 1
    assert combos == len(day_sets) * len(time_sets) == 40
    assert len(rules) == 3 * 91
    assert outcomes == {True, False}


def test_availability_filter_selects_tutors_with_a_matching_rule(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    viewer = add_user(sm)
    thursday_evening = add_tutor(sm, rules=((4, 1020, 1200),)).profile_id
    monday_morning = add_tutor(sm, rules=((1, 540, 660),)).profile_id
    # Ends exactly when the evening bucket starts: half-open, so no match.
    thursday_afternoon = add_tutor(sm, rules=((4, 840, 1020),)).profile_id

    def matching(days: frozenset[int], times: frozenset[str]) -> set[uuid.UUID]:
        filters = DirectoryFilters(days=days, times=times)  # type: ignore[arg-type]
        page = repo.list_for_viewer(viewer, "student", filters, after=None, limit=50)
        return set(_ids(page.items))

    every = {thursday_evening, monday_morning, thursday_afternoon}
    assert matching(frozenset(), frozenset()) == every
    assert matching(frozenset({4}), frozenset({"evening"})) == {thursday_evening}
    assert matching(frozenset(), frozenset({"morning"})) == {monday_morning}
    assert matching(frozenset({4}), frozenset()) == {thursday_evening, thursday_afternoon}
    assert matching(frozenset({2}), frozenset()) == set()


def test_list_public_refuses_availability_filters(sm: sessionmaker[Session]) -> None:
    """Row 5b: the public directory has no availability filter."""
    repo = TutorDirectoryRepository(sm)
    with pytest.raises(ValueError, match="availability"):
        repo.list_public(DirectoryFilters(days=frozenset({1})), after=None, limit=20)


# ---------------------------------------------------------------------------
# Other filters and facets
# ---------------------------------------------------------------------------


def test_subject_mode_and_area_filters(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    maths, physics = add_subject(sm, name="Mathematics"), add_subject(sm, name="Physics")
    a = add_tutor(sm, subjects=(maths,), modes=("virtual",), area="cairo").profile_id
    b = add_tutor(sm, subjects=(physics,), modes=("in_person",), area="giza").profile_id
    c = add_tutor(
        sm, subjects=(maths, physics), modes=("other",), other_mode_note=None, area="giza"
    ).profile_id

    def matching(**kwargs: object) -> set[uuid.UUID]:
        page = repo.list_public(DirectoryFilters(**kwargs), after=None, limit=50)  # type: ignore[arg-type]
        return set(_ids(page.items))

    assert matching(subject=maths) == {a, c}
    assert matching(subject="NOPE") == set()
    assert matching(modes=frozenset({"in_person", "other"})) == {b, c}
    assert matching(modes=frozenset({"virtual"})) == {a}
    assert matching(area="giza") == {b, c}
    assert matching(area="giza", subject=maths, modes=frozenset({"other"})) == {c}


def test_cards_carry_subjects_modes_and_rating_inputs(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    zoology, algebra = add_subject(sm, name="Zoology"), add_subject(sm, name="Algebra")
    seeded = add_tutor(
        sm, subjects=(zoology, algebra), modes=("in_person", "virtual"), rating=(14, 3)
    )
    (card,) = repo.list_public(DirectoryFilters(), after=None, limit=20).items
    assert card.tutor_id == seeded.profile_id
    assert [s.name for s in card.subjects] == ["Algebra", "Zoology"]
    assert card.modes == ("virtual", "in_person")
    assert (card.rating_sum, card.rating_count) == (14, 3)
    assert card.public_first_name == "Sara"
    assert card.public_last_initial == "M"


def test_facets_cover_visible_tutors_only(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    shown, hidden = add_subject(sm, name="Chemistry"), add_subject(sm, name="Biology")
    add_tutor(sm, subjects=(shown,), area="cairo")
    add_tutor(sm, subjects=(hidden,), area="giza", paused=True)
    add_tutor(sm, subjects=(hidden,), area="aswan", state="pending_review")
    facets = repo.facets()
    assert [s.code for s in facets.subjects] == [shown]
    assert facets.area_codes == ("cairo",)
    first = repo.list_public(DirectoryFilters(), after=None, limit=1)
    assert first.facets == facets


# ---------------------------------------------------------------------------
# Block anti-join (O11, through active_block_between_sql)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["student_blocks_tutor", "tutor_blocks_student"])
def test_block_anti_join_hides_blocked_tutor_for_student(
    sm: sessionmaker[Session], direction: str
) -> None:
    repo = TutorDirectoryRepository(sm)
    student, other_student = add_user(sm), add_user(sm)
    parent = add_user(sm, Role.parent)
    blocked, free = add_tutor(sm), add_tutor(sm)
    # Blocks are keyed on users: the tutor side is the profile's user, never the profile.
    assert blocked.profile_id != blocked.user_id
    if direction == "student_blocks_tutor":
        add_block(sm, student, blocked.user_id)
    else:
        add_block(sm, blocked.user_id, student)

    def visible(viewer: uuid.UUID, role: str) -> set[uuid.UUID]:
        page = repo.list_for_viewer(viewer, role, DirectoryFilters(), after=None, limit=50)
        return set(_ids(page.items))

    assert visible(student, "student") == {free.profile_id}
    assert repo.profile_for_viewer(blocked.profile_id, student, "student") is None
    assert repo.profile_for_viewer(free.profile_id, student, "student") is not None
    # Nobody else is affected: another student, a parent (who holds no blocks), the public.
    assert visible(other_student, "student") == {blocked.profile_id, free.profile_id}
    assert visible(parent, "parent") == {blocked.profile_id, free.profile_id}
    public = repo.list_public(DirectoryFilters(), after=None, limit=50)
    assert set(_ids(public.items)) == {blocked.profile_id, free.profile_id}
    assert repo.public_card(blocked.profile_id) is not None

    # Unblocking (removed_at set) restores the tutor.
    if direction == "student_blocks_tutor":
        set_block_removed(sm, student, blocked.user_id)
    else:
        set_block_removed(sm, blocked.user_id, student)
    assert visible(student, "student") == {blocked.profile_id, free.profile_id}
    assert repo.profile_for_viewer(blocked.profile_id, student, "student") is not None


def test_profile_for_viewer_hides_unlisted_and_paused(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    viewer = add_user(sm)
    for state in ("draft", "pending_review", "rejected", "suspended", "closed"):
        hidden = add_tutor(sm, state=state)
        assert repo.profile_for_viewer(hidden.profile_id, viewer, "student") is None, state
        assert repo.public_card(hidden.profile_id) is None, state
    paused = add_tutor(sm, paused=True)
    assert repo.profile_for_viewer(paused.profile_id, viewer, "parent") is None
    assert repo.public_card(paused.profile_id) is None
    assert repo.profile_for_viewer(uuid.uuid4(), viewer, "student") is None


def test_profile_for_viewer_reads_the_logged_in_fields(sm: sessionmaker[Session]) -> None:
    repo = TutorDirectoryRepository(sm)
    viewer = add_user(sm)
    first = NOW - timedelta(days=100)
    seeded = add_tutor(
        sm,
        bio="Ten years of IGCSE teaching.",
        qualification_note="PGCE",
        modes=("virtual", "other"),
        other_mode_note="Small groups",
        rules=((4, 1020, 1200), (1, 540, 600)),
        first_listed_at=first,
        documents_seen=True,
    )
    view = repo.profile_for_viewer(seeded.profile_id, viewer, "student")
    assert view is not None
    assert view.bio == "Ten years of IGCSE teaching."
    assert view.qualification_note == "PGCE"
    assert view.other_mode_note == "Small groups"
    assert view.documents_seen is True
    assert view.zone == "Africa/Cairo"
    assert view.first_listed_at == first
    assert [(r.iso_weekday, r.start_minute, r.end_minute) for r in view.availability] == [
        (1, 540, 600),
        (4, 1020, 1200),
    ]


# ---------------------------------------------------------------------------
# Query budget (SPEC §e.3, F24)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tutors", [3, 7])
def test_query_budget_first_page_3_later_pages_2(sm: sessionmaker[Session], tutors: int) -> None:
    repo = TutorDirectoryRepository(sm)
    subjects = [add_subject(sm, name=f"Subject {n}") for n in range(3)]
    viewer = add_user(sm)
    for n in range(tutors):
        add_tutor(sm, subjects=subjects[: 1 + n % 3], rank=Decimal(f"4.{n}00000"))
    repo.list_public(DirectoryFilters(), after=None, limit=2)  # warm the pool

    for run in (
        lambda after: repo.list_public(DirectoryFilters(), after=after, limit=2),
        lambda after: repo.list_for_viewer(
            viewer, "student", DirectoryFilters(), after=after, limit=2
        ),
    ):
        with count_statements(sm) as first_page:
            page = run(None)
        assert len(page.items) == 2
        assert page.facets is not None
        assert len(first_page) == 3, first_page
        assert page.next_key is not None
        with count_statements(sm) as later_page:
            second = run(page.next_key)
        assert second.facets is None
        assert len(second.items) >= 1
        assert len(later_page) == 2, later_page


@pytest.mark.parametrize("subject_count", [1, 3])
def test_p2_sp2_two_statements(sm: sessionmaker[Session], subject_count: int) -> None:
    repo = TutorDirectoryRepository(sm)
    subjects = [add_subject(sm, name=f"Subject {n}") for n in range(subject_count)]
    viewer = add_user(sm)
    seeded = add_tutor(sm, subjects=subjects, rules=((1, 540, 600), (2, 540, 600), (3, 540, 600)))
    repo.public_card(seeded.profile_id)  # warm the pool

    with count_statements(sm) as public:
        card = repo.public_card(seeded.profile_id)
    assert card is not None
    assert len(card.card.subjects) == subject_count
    assert len(public) == 2, public

    with count_statements(sm) as logged_in:
        view = repo.profile_for_viewer(seeded.profile_id, viewer, "student")
    assert view is not None
    assert len(view.availability) == 3
    assert len(logged_in) == 2, logged_in
