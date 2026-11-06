"""The block rows: B1-B3 at the repository (PLAN T21; SPEC §a.2 ``tutoring_blocks``, §i.8, O13).

* **Rows are never deleted.** A lift sets ``removed_at``; a re-block clears it and keeps
  ``created_at`` (the first block, which the outcome hold reads, ADR-T04), so "this student ever
  blocked this tutor" stays answerable.
* **``updated_at`` is the instant the row last became active** (SPEC §i.8). The block INSERT
  takes the server default; a lift and a renewal set ``updated_at = now()`` themselves (raw SQL
  skips the ORM ``onupdate``); a block request on a row that is already active writes nothing
  at all (``xmin`` unchanged), so a repeated press cannot move ``blocked_since``.
* **Who may block whom (O13).** A student blocks a tutor profile by its id: one that is listed
  and not paused, or one they have booked, shared with or blocked before. A tutor blocks only a
  student who booked or granted them. Neither rule reads the other side's block.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.tutor_directory import student_label
from lemely.db.models.enums import GrantRevokeReason, Role
from lemely.db.tutoring_blocks_repo import BlockCaller, NoBlockRow, NotBlockable, TutorInactive
from lemely.db.tutoring_predicates import student_ever_blocked_tutor_sql
from tests.test_booking_repo import (
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    set_listing,
    stored,
)
from tests.test_tutor_grant_repo import add_grant
from tests.test_tutoring_sweeps import (
    SIDES,
    Side,
    add_class,
    block,
    block_count,
    block_row,
    blocks,
    classes_of,
    enrol,
    pair,
    student_caller,
    tutor_caller,
)
from tests.tutoring_db import SeededTutor, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def caller_of(tutor: SeededTutor, student: uuid.UUID, by: Side) -> tuple[BlockCaller, uuid.UUID]:
    """The caller and the counterpart id B2/B3 take for a block made by ``by``."""
    if by == "student":
        return student_caller(student), tutor.profile_id
    return tutor_caller(tutor), student


def ever_blocked(sm: sessionmaker[Session], student: uuid.UUID, tutor_user: uuid.UUID) -> bool:
    """The outcome exclusion's question, through the shared predicate."""
    with sm() as session:
        return bool(
            session.execute(
                sa.text(f"SELECT {student_ever_blocked_tutor_sql(':s', ':t')}"),
                {"s": student, "t": tutor_user},
            ).scalar_one()
        )


# ---------------------------------------------------------------------------
# Never deleted; re-block clears removed_at
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("by", SIDES)
def test_reblock_clears_removed_at_and_keeps_the_first_block(
    sm: sessionmaker[Session], by: Side
) -> None:
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    caller, counterpart = caller_of(w.tutor, w.student, by)
    repo = blocks(sm)
    key = pair(w.tutor, w.student, by=by)

    first = repo.block(caller, counterpart)
    made = block_row(sm, *key)
    assert repo.unblock(caller, counterpart) is True
    lifted = block_row(sm, *key)
    again = repo.block(caller, counterpart)
    renewed = block_row(sm, *key)

    assert made is not None
    assert lifted is not None
    assert renewed is not None
    assert first.created
    assert again.created  # a renewed block is a new block: its sweep runs
    assert again.sweep is not None
    assert lifted[2] is not None
    assert renewed[2] is None  # removed_at cleared
    assert renewed[0] == made[0]  # created_at: still the first block
    assert renewed[1] > lifted[1] > made[1]  # updated_at: the instant it last became active
    assert again.block.active_since == renewed[1]
    assert block_count(sm) == 1


def test_rows_are_never_deleted(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    repo = blocks(sm)
    me = student_caller(w.student)
    repo.block(me, w.tutor.profile_id)
    repo.unblock(me, w.tutor.profile_id)
    repo.unblock(me, w.tutor.profile_id)

    row = block_row(sm, w.student, w.tutor.user_id)
    assert row is not None
    assert row[2] is not None
    assert block_count(sm) == 1
    assert repo.active_blocks(me) == []
    assert ever_blocked(sm, w.student, w.tutor.user_id) is True


@pytest.mark.parametrize("by", SIDES)
def test_block_on_an_active_row_writes_nothing(sm: sessionmaker[Session], by: Side) -> None:
    """SPEC §i.8: B2 on an active block answers with it and touches nothing, not even the row
    (``xmin``) and not the sweeps: a class re-joined while blocked (accepted, §i.3) stays."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    caller, counterpart = caller_of(w.tutor, w.student, by)
    repo = blocks(sm)
    first = repo.block(caller, counterpart)
    row = block_row(sm, *pair(w.tutor, w.student, by=by))
    rejoined = add_class(sm, w.tutor.user_id)
    enrol(sm, rejoined, w.student)

    again = repo.block(caller, counterpart)

    assert first.created
    assert again.created is False
    assert again.sweep is None
    assert again.block == first.block
    assert block_row(sm, *pair(w.tutor, w.student, by=by)) == row
    assert classes_of(sm, w.student) == {rejoined}


def test_unblock_sets_removed_at_and_updated_at_to_the_lift(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    repo = blocks(sm)
    me = student_caller(w.student)
    repo.block(me, w.tutor.profile_id)
    made = block_row(sm, w.student, w.tutor.user_id)

    assert repo.unblock(me, w.tutor.profile_id) is True

    lifted = block_row(sm, w.student, w.tutor.user_id)
    assert made is not None
    assert lifted is not None
    assert lifted[2] is not None
    assert lifted[1] == lifted[2]  # updated_at = removed_at = the lift's now()
    assert lifted[0] == made[0]


def test_unblock_of_a_lifted_row_writes_nothing(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    repo = blocks(sm)
    me = student_caller(w.student)
    repo.block(me, w.tutor.profile_id)
    repo.unblock(me, w.tutor.profile_id)
    lifted = block_row(sm, w.student, w.tutor.user_id)

    assert repo.unblock(me, w.tutor.profile_id) is False
    assert block_row(sm, w.student, w.tutor.user_id) == lifted


def test_unblock_without_a_row_of_the_callers_is_no_block_row(sm: sessionmaker[Session]) -> None:
    """O28: only the caller's own rows; the other side's block of the caller is not one."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    repo = blocks(sm)
    repo.block(tutor_caller(w.tutor), w.student)  # the tutor's row, not the student's

    for caller, counterpart in (
        (student_caller(w.student), w.tutor.profile_id),
        (student_caller(w.student), uuid.uuid4()),
        (student_caller(w.student), w.tutor.user_id),  # a users.id is not a profile id
        (tutor_caller(w.tutor), uuid.uuid4()),
    ):
        with pytest.raises(NoBlockRow):
            repo.unblock(caller, counterpart)
    assert block_row(sm, w.tutor.user_id, w.student) is not None
    assert block_row(sm, w.tutor.user_id, w.student)[2] is None  # type: ignore[index]


# ---------------------------------------------------------------------------
# B1
# ---------------------------------------------------------------------------


def test_active_blocks_lists_only_the_callers_active_rows(sm: sessionmaker[Session]) -> None:
    student = add_student(sm)
    blocked_now = add_tutor(sm, first_name="Tamer", initial="K")
    lifted = add_tutor(sm, first_name="Lina")
    blocked_me = add_tutor(sm, first_name="Omar")
    add_grant(sm, student, blocked_me)
    repo = blocks(sm)
    me = student_caller(student)
    repo.block(me, blocked_now.profile_id)
    repo.block(me, lifted.profile_id)
    repo.unblock(me, lifted.profile_id)
    repo.block(tutor_caller(blocked_me), student)

    mine = repo.active_blocks(me)
    assert [(item.counterpart_id, item.display_name) for item in mine] == [
        (blocked_now.profile_id, "Tamer K.")
    ]
    tutors_view = repo.active_blocks(tutor_caller(blocked_me))
    assert [(item.counterpart_id, item.display_name) for item in tutors_view] == [
        (student, student_label(None, student))
    ]
    row = block_row(sm, student, blocked_now.user_id)
    assert row is not None
    assert mine[0].active_since == row[1]


def test_active_blocks_newest_first(sm: sessionmaker[Session]) -> None:
    student = add_student(sm)
    older, newer = add_tutor(sm, first_name="Hana"), add_tutor(sm, first_name="Rami")
    repo = blocks(sm)
    me = student_caller(student)
    repo.block(me, older.profile_id)
    repo.block(me, newer.profile_id)
    assert [item.counterpart_id for item in repo.active_blocks(me)] == [
        newer.profile_id,
        older.profile_id,
    ]


# ---------------------------------------------------------------------------
# O13: who may block whom
# ---------------------------------------------------------------------------


def test_o13_student_may_block_a_listed_tutor_or_one_they_know(sm: sessionmaker[Session]) -> None:
    student = add_student(sm)
    listed = add_tutor(sm)
    draft_unknown = add_tutor(sm, state="draft")
    paused_unknown = add_tutor(sm, paused=True)
    w = make_world(sm)  # a tutor this student books below
    suspended_shared = add_tutor(sm, state="suspended")
    add_grant(sm, student, suspended_shared, revoked=GrantRevokeReason.tutor_suspended)
    booked_tutor = w.tutor
    add_booking(sm, w, state="cancelled", starts_in=-timedelta(days=4), student=student)
    set_listing(sm, booked_tutor, "draft")
    lifted_then_paused = add_tutor(sm)
    repo = blocks(sm)
    me = student_caller(student)
    repo.block(me, lifted_then_paused.profile_id)
    repo.unblock(me, lifted_then_paused.profile_id)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE tutor_profiles SET paused_at = now() WHERE id = :t"),
            {"t": lifted_then_paused.profile_id},
        )

    for refused in (uuid.uuid4(), draft_unknown.profile_id, paused_unknown.profile_id):
        with pytest.raises(NotBlockable):
            repo.block(me, refused)
    for allowed in (
        listed.profile_id,
        suspended_shared.profile_id,
        booked_tutor.profile_id,
        lifted_then_paused.profile_id,
    ):
        assert repo.block(me, allowed).created, allowed
    assert block_row(sm, student, draft_unknown.user_id) is None


def test_o13_the_students_rule_ignores_the_tutors_block(sm: sessionmaker[Session]) -> None:
    """No oracle: a tutor who blocked the student is blockable by them exactly as one who did
    not (the student's rule reads the listing and the student's own history, never a block of
    the student)."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    repo = blocks(sm)
    repo.block(tutor_caller(w.tutor), w.student)
    assert repo.block(student_caller(w.student), w.tutor.profile_id).created


def test_o13_tutor_may_block_only_students_who_booked_or_granted(
    sm: sessionmaker[Session],
) -> None:
    w = make_world(sm)
    booked = w.student
    add_booking(sm, w, state="expired", starts_in=-timedelta(days=4))
    child = add_student(sm)
    parent = add_parent(sm, child)
    add_booking(sm, w, state="declined", student=child, requested_by=parent, party="parent")
    granted = add_student(sm)
    add_grant(sm, granted, w.tutor, revoked=GrantRevokeReason.student)
    stranger = add_student(sm)
    other_tutor = another_tutor(sm, w.subject)
    others_student = add_student(sm)
    add_booking(
        sm,
        w,
        state="completed",
        starts_in=-timedelta(days=2),
        tutor=other_tutor,
        student=others_student,
    )
    teacher = add_user(sm, Role.teacher)
    repo = blocks(sm)
    me = tutor_caller(w.tutor)

    for refused in (stranger, others_student, teacher, parent, uuid.uuid4()):
        with pytest.raises(NotBlockable):
            repo.block(me, refused)
    for allowed in (booked, child, granted):
        assert repo.block(me, allowed).created
    assert block_count(sm) == 3


@pytest.mark.parametrize(
    ("state", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
def test_an_inactive_tutor_may_not_block_and_nothing_is_written(
    sm: sessionmaker[Session], state: str, code: str
) -> None:
    w = make_world(sm)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    set_listing(sm, w.tutor, state)

    with pytest.raises(TutorInactive) as refused:
        block(sm, w.tutor, w.student, by="tutor")

    assert (refused.value.code, refused.value.status) == (code, 409)
    assert block_count(sm) == 0
    assert stored(sm, upcoming).cancelled_at is None


def test_each_side_holds_its_own_row(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    assert block(sm, w.tutor, w.student, by="tutor").created
    assert block(sm, w.tutor, w.student, by="student").created
    assert block_count(sm) == 2
