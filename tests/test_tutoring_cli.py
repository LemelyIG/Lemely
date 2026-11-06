"""`lemely tutoring recompute-ratings [--tutor <id>]` (SPEC §f numbering note, F35, O-12).

The expected aggregate is never read from the code under test: ``expected_ratings``
(``tests/test_tutor_review_repo.py``) reads the raw review rows and feeds them to
``core.tutor_ratings``, and the hand-computed literals below are pinned beside it.

``lemely/app/cli.py`` is a hot file the lead owns, so these tests drive
``tutoring_cli.recompute_ratings_command`` through a click group built the way the
registration in ``cli.py`` is (same option, same call). The lead checks the
registration itself at integration.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import click
import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from lemely.app.tutoring_cli import recompute_ratings_command
from tests.test_tutor_review_repo import (
    add_booking,
    add_review_row,
    add_student,
    expected_ratings,
    stored_ratings,
)
from tests.tutoring_db import SeededTutor, add_subject, add_tutor, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import Result
    from sqlalchemy.orm import Session, sessionmaker

Ratings = tuple[int, int, Decimal]


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def invoke(sm: sessionmaker[Session], *args: str, json_output: bool = False) -> Result:
    """Run the command the way ``lemely tutoring recompute-ratings`` registers it."""

    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json_output"] = json_output

    @root.group("tutoring")
    def tutoring_group() -> None:
        """Tutoring marketplace maintenance."""

    @tutoring_group.command("recompute-ratings")
    @click.option("--tutor", "tutor", default=None)
    @click.pass_context
    def command(ctx: click.Context, tutor: str | None) -> None:
        recompute_ratings_command(
            sm, tutor=tutor, json_output=bool(ctx.obj.get("json_output", False))
        )

    return CliRunner().invoke(root, ["tutoring", "recompute-ratings", *args])


@dataclass(frozen=True)
class Seeded:
    tutor: SeededTutor
    corrupted: Ratings
    truth: Ratings  # hand-computed: (5 * 4.0 + sum) / (5 + count)


def corrupt(sm: sessionmaker[Session], tutor_id: uuid.UUID, stored: Ratings) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET rating_sum = :s, rating_count = :c, rank_score = :r "
                "WHERE id = :t"
            ),
            {"s": stored[0], "c": stored[1], "r": stored[2], "t": tutor_id},
        )


def seed_three_tutors(sm: sessionmaker[Session]) -> tuple[Seeded, Seeded, Seeded]:
    subject = add_subject(sm)
    now = datetime.now(UTC)

    def review(
        tutor: SeededTutor,
        student: uuid.UUID,
        stars: int,
        *,
        age_days: int,
        removed: bool = False,
    ) -> None:
        add_review_row(
            sm,
            booking=add_booking(
                sm,
                student=student,
                tutor=tutor,
                subject=subject,
                ended_ago=timedelta(days=age_days + 8),
            ),
            tutor_id=tutor.profile_id,
            student=student,
            stars=stars,
            created_at=now - timedelta(days=age_days),
            removed=removed,
        )

    # Tutor A: three students (5, 4, 3) and one removed 1-star review that must not count.
    a = add_tutor(sm, subjects=(subject,))
    for stars, age in ((5, 5), (4, 4), (3, 3)):
        review(a, add_student(sm), stars, age_days=age)
    review(a, add_student(sm), 1, age_days=2, removed=True)
    # Tutor B: one student who reviewed twice; only the latest (5) counts, once.
    b = add_tutor(sm, subjects=(subject,))
    repeat = add_student(sm)
    review(b, repeat, 1, age_days=30)
    review(b, repeat, 5, age_days=10)
    # Tutor C: no reviews at all, yet a stored aggregate.
    c = add_tutor(sm, subjects=(subject,))

    seeded = (
        Seeded(a, corrupted=(3, 3, Decimal("3.000000")), truth=(12, 3, Decimal("4.000000"))),
        Seeded(b, corrupted=(10, 2, Decimal("4.900000")), truth=(5, 1, Decimal("4.166667"))),
        Seeded(c, corrupted=(9, 3, Decimal("4.500000")), truth=(0, 0, Decimal("4.000000"))),
    )
    for item in seeded:
        corrupt(sm, item.tutor.profile_id, item.corrupted)
    return seeded


def test_cli_recompute_all_restores_corrupted_aggregates_of_every_tutor(
    sm: sessionmaker[Session],
) -> None:
    seeded = seed_three_tutors(sm)
    for item in seeded:  # non-vacuity: each tutor really is wrong before the run
        assert stored_ratings(sm, item.tutor.profile_id) == item.corrupted
        assert expected_ratings(sm, item.tutor.profile_id) != item.corrupted

    result = invoke(sm)
    assert result.exit_code == 0, result.output

    for item in seeded:
        restored = stored_ratings(sm, item.tutor.profile_id)
        assert restored == expected_ratings(sm, item.tutor.profile_id)  # the independent oracle
        assert restored == item.truth  # the hand-computed literal
    assert "checked=3 corrected=3" in result.output
    for item in seeded:
        assert str(item.tutor.profile_id) in result.output


def test_cli_recompute_single_tutor_touches_only_that_tutor(sm: sessionmaker[Session]) -> None:
    a, b, c = seed_three_tutors(sm)
    result = invoke(sm, "--tutor", str(b.tutor.profile_id))
    assert result.exit_code == 0, result.output
    assert stored_ratings(sm, b.tutor.profile_id) == b.truth
    assert stored_ratings(sm, a.tutor.profile_id) == a.corrupted  # still wrong: not touched
    assert stored_ratings(sm, c.tutor.profile_id) == c.corrupted
    assert "checked=1 corrected=1" in result.output
    assert str(a.tutor.profile_id) not in result.output


def test_cli_recompute_is_idempotent(sm: sessionmaker[Session]) -> None:
    seeded = seed_three_tutors(sm)
    assert invoke(sm).exit_code == 0
    second = invoke(sm)
    assert second.exit_code == 0, second.output
    assert "checked=3 corrected=0" in second.output
    for item in seeded:
        assert stored_ratings(sm, item.tutor.profile_id) == item.truth


def test_cli_json_output(sm: sessionmaker[Session]) -> None:
    a, b, c = seed_three_tutors(sm)
    result = invoke(sm, json_output=True)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert (payload["checked"], payload["corrected"]) == (3, 3)
    by_id = {row["tutorId"]: row for row in payload["tutors"]}
    assert set(by_id) == {str(x.tutor.profile_id) for x in (a, b, c)}
    row = by_id[str(b.tutor.profile_id)]
    assert (row["before"], row["after"]) == (
        {"ratingSum": 10, "ratingCount": 2, "rankScore": "4.900000"},
        {"ratingSum": 5, "ratingCount": 1, "rankScore": "4.166667"},
    )
    assert row["changed"] is True


def test_cli_unknown_or_malformed_tutor_id_fails_without_writing(
    sm: sessionmaker[Session],
) -> None:
    a, _b, _c = seed_three_tutors(sm)
    unknown = invoke(sm, "--tutor", str(uuid.uuid4()))
    assert unknown.exit_code != 0
    assert "No tutor profile" in unknown.output
    malformed = invoke(sm, "--tutor", "not-a-uuid")
    assert malformed.exit_code != 0
    assert "not a valid" in malformed.output.lower()
    assert stored_ratings(sm, a.tutor.profile_id) == a.corrupted


def test_cli_with_no_tutors_reports_zero(sm: sessionmaker[Session]) -> None:
    result = invoke(sm)
    assert result.exit_code == 0, result.output
    assert "checked=0 corrected=0" in result.output
