"""The reference loaders must hit the database once per process, not per call.

`get_taxonomy` is called once per classified question. A cache miss per call
would turn `question_bank_repo.backfill_topics` from one file parse into one
round trip per row, which is the regression this test exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lemely.io.paper_timing as paper_timing
import lemely.io.syllabus_topics as syllabus_topics

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class _CountingSession:
    """Wraps a real session and counts `execute`/`scalars` calls."""

    def __init__(self, inner: Session) -> None:
        self._inner = inner
        self.queries = 0

    def scalars(self, *args: object, **kwargs: object) -> object:
        self.queries += 1
        return self._inner.scalars(*args, **kwargs)

    def execute(self, *args: object, **kwargs: object) -> object:
        self.queries += 1
        return self._inner.execute(*args, **kwargs)


def test_taxonomy_is_cached_after_the_first_load(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    syllabus_topics.invalidate_reference_cache()
    with migrated_sessionmaker() as raw:
        counting = _CountingSession(raw)
        first = syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        after_first = counting.queries
        for _ in range(20):
            syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        assert first is not None
        assert counting.queries == after_first, (
            "every call after the first must be served from cache"
        )


def test_invalidate_forces_a_reload(migrated_sessionmaker: sessionmaker[Session]) -> None:
    syllabus_topics.invalidate_reference_cache()
    with migrated_sessionmaker() as raw:
        counting = _CountingSession(raw)
        syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        before = counting.queries
        syllabus_topics.invalidate_reference_cache()
        syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        assert counting.queries > before


def test_paper_timings_still_exclude_practicals_by_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    paper_timing.invalidate_reference_cache()
    with migrated_sessionmaker() as s:
        assert set(paper_timing.get_paper_timings("0625", session=s)) == {1, 2, 3, 4}
        assert set(paper_timing.get_paper_timings("0625", include_practical=True, session=s)) == {
            1,
            2,
            3,
            4,
            5,
            6,
        }
        assert paper_timing.get_paper_timings("9999", session=s) == {}
