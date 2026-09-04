"""Loader for CAIE paper timing facts, backed by ``syllabus_papers``.

Was bundled static JSON; the table is the source of truth now (spec D1), so a
subject can be added without a deploy. The public shape is deliberately
unchanged — same function names, same ``dict[int, PaperTiming]`` return, same
practical-exclusion policy — so the placement assembler did not have to change.

Only ``duration_minutes`` and ``total_marks`` are stored. The minutes-per-mark
rate a placement estimate needs is computed from them
(:attr:`~lemely.core.placement.PaperTiming.minutes_per_mark`) and never
written down, so every stored number is one a human can check against the
syllabus PDF named in ``source_document``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.placement import PaperTiming
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.session import get_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_lock = threading.Lock()
_cache: dict[tuple[str, str], dict[int, PaperTiming]] | None = None


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the seeding and ingest paths."""
    global _cache
    with _lock:
        _cache = None


def _load(session: Session) -> dict[tuple[str, str], dict[int, PaperTiming]]:
    out: dict[tuple[str, str], dict[int, PaperTiming]] = {}
    for row in session.scalars(sa.select(SyllabusPaper)):
        timing = PaperTiming(
            board=row.board.value,
            subject_code=row.subject_code,
            paper_number=row.paper_number,
            duration_minutes=row.duration_minutes,
            total_marks=row.total_marks,
            practical=row.practical,
            source_document=row.source_document,
            syllabus_version=row.syllabus_version,
        )
        out.setdefault((timing.board, timing.subject_code), {})[timing.paper_number] = timing
    return out


def load_paper_timings(
    session: Session | None = None,
) -> dict[tuple[str, str], dict[int, PaperTiming]]:
    """Every timing, keyed ``(board, subject_code)`` → ``paper_number``.

    Cached per process: call :func:`invalidate_reference_cache` after
    anything that writes ``syllabus_papers`` (currently only migration 0024's
    one-time insert, which runs before this process is up). Neither the
    seeder nor any other runtime path writes this table today, so neither
    calls the invalidator — doing so would be a no-op dressed up as caution.
    """
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded = _load(session) if session is not None else _load_with_own_session()
    with _lock:
        _cache = loaded
    return loaded


def _load_with_own_session() -> dict[tuple[str, str], dict[int, PaperTiming]]:
    with get_sessionmaker()() as session:
        return _load(session)


def get_paper_timings(
    subject_code: str,
    *,
    board: str = "caie",
    include_practical: bool = False,
    session: Session | None = None,
) -> dict[int, PaperTiming]:
    """Timings for one subject, keyed by paper number.

    An empty mapping is a normal outcome, not an error: a subject whose
    Assessment overview has not been transcribed has no eligible placement
    questions, which is what the caller should report.

    Practical papers (0625 Papers 5/6) are excluded by default. Their questions
    assume apparatus in front of the candidate, so a practical question in an
    at-home placement test measures whether the student owns a ripple tank. The
    rows are still stored — this is an assembly policy, not a claim the data is
    wrong.
    """
    timings = load_paper_timings(session).get((board, subject_code), {})
    if include_practical:
        return dict(timings)
    return {number: t for number, t in timings.items() if not t.practical}
