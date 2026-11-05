"""Tutoring maintenance commands: ``lemely tutoring recompute-ratings [--tutor <id>]``.

A tutor's stored rating (``rating_sum``, ``rating_count``, ``rank_score``) is
rewritten from their reviews by the same function every review change uses,
:meth:`lemely.db.tutor_review_repo.TutorReviewRepository.recompute_ratings_report`
(SPEC §f numbering note, F35, O-12), so this command can only ever put back what the
next review change would have written. It repairs a stored value that went wrong
(a restored backup, a manual edit, a bug) and is safe to run at any time: each tutor
is recomputed in its own short transaction under the tutor-row lock, and a tutor
whose stored value is already right is not written.

``recompute_ratings_command`` is registered in ``lemely/app/cli.py``; it takes the
session factory (rather than settings) so tests need no monkeypatching.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import click

from lemely.db.tutor_review_repo import ReviewNotFoundError, TutorReviewRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.tutor_review_repo import RatingRecompute


def _payload(result: RatingRecompute) -> dict[str, object]:
    return {
        "tutorId": str(result.tutor_profile_id),
        "changed": result.changed,
        "before": {
            "ratingSum": result.before_sum,
            "ratingCount": result.before_count,
            "rankScore": format(result.before_rank, "f"),
        },
        "after": {
            "ratingSum": result.after_sum,
            "ratingCount": result.after_count,
            "rankScore": format(result.after_rank, "f"),
        },
    }


def _tutor_ids(repo: TutorReviewRepository, tutor: str | None) -> list[uuid.UUID]:
    if tutor is None:
        return repo.tutor_profile_ids()
    try:
        return [uuid.UUID(tutor)]
    except ValueError:
        raise click.BadParameter(
            f"{tutor!r} is not a valid tutor profile id.", param_hint="--tutor"
        ) from None


def recompute_ratings_command(
    sessionmaker: sessionmaker[Session], *, tutor: str | None, json_output: bool
) -> None:
    """Recompute and store every tutor's rating, or only ``tutor``'s (a tutor profile id).

    Prints one line per corrected tutor and a ``checked=N corrected=M`` summary, or the
    same as JSON. An unknown ``tutor`` is a :class:`click.ClickException`, and nothing
    is written for a malformed one.
    """
    repo = TutorReviewRepository(sessionmaker)
    results: list[RatingRecompute] = []
    for tutor_id in _tutor_ids(repo, tutor):
        try:
            results.append(repo.recompute_ratings_report(tutor_id))
        except ReviewNotFoundError:
            raise click.ClickException(f"No tutor profile with id {tutor_id}.") from None
    corrected = sum(1 for result in results if result.changed)
    if json_output:
        click.echo(
            json.dumps(
                {
                    "checked": len(results),
                    "corrected": corrected,
                    "tutors": [_payload(result) for result in results],
                },
                indent=2,
            )
        )
        return
    for result in results:
        if result.changed:
            click.echo(
                f"{result.tutor_profile_id}: "
                f"sum {result.before_sum} -> {result.after_sum}, "
                f"count {result.before_count} -> {result.after_count}, "
                f"rank {result.before_rank} -> {result.after_rank}"
            )
    click.echo(f"checked={len(results)} corrected={corrected}")


__all__ = ["recompute_ratings_command"]
