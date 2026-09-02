"""CAIE grade boundary resolver, backed by ``component_thresholds``.

Was bundled static JSON; the table is the source of truth now (Task 12's
ingest wrote 1,354 component rows and 716 option rows, 2006-2026). The public
shape is deliberately unchanged — ``resolve`` still returns the same
``(dict[str, float], BoundarySource)`` pair via the same three-rung fallback
chain — because ``attempts.boundary_source`` records which rung answered on
every graded paper ever recorded, and that three-way distinction is a stored
fact, not an implementation detail free to change.

Only raw marks and ``max_mark`` are stored; percentages are computed from them
at read time (:func:`_percentages`) and never written down, so every stored
number stays one a human can check against the source PDF.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from statistics import mean
from typing import TYPE_CHECKING, Literal

import sqlalchemy as sa

from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold
from lemely.db.session import get_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.schemas import ExamMetadata

# Maps ExamMetadata.session_month values to the short session code used in boundary keys.
_SESSION_CODE: dict[str, str] = {
    "May/June": "m",
    "Oct/Nov": "w",
    "Feb/Mar": "s",
    "Specimen": "sp",
}

# The reverse mapping, keyed on the ORM enum, for building keys from stored rows.
_SESSION_CODE_BY_MONTH: dict[SessionMonth, str] = {
    SessionMonth.may_june: "m",
    SessionMonth.oct_nov: "w",
    SessionMonth.feb_mar: "s",
    SessionMonth.specimen: "sp",
}

BoundarySource = Literal["exact", "subject_default", "global_default"]

_lock = threading.Lock()
_ReferenceTuple = tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, float]]
_cache: _ReferenceTuple | None = None

_FALLBACK_GLOBAL: dict[str, float] = {
    "A": 80.0,
    "B": 70.0,
    "C": 60.0,
    "D": 50.0,
    "E": 40.0,
}


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the ingest path."""
    global _cache
    with _lock:
        _cache = None


def _make_key(metadata: ExamMetadata) -> str | None:
    """Derive the exact boundary lookup key from ExamMetadata.

    Returns None when session_year is None (caller skips exact lookup).
    Specimen papers have no real session boundaries; they always return None.

    Example: subject_code='0625', session_month='May/June', session_year=2020,
             paper_number=1, paper_variant=2 → '0625_m20_p12'
    """
    if metadata.session_year is None:
        return None
    if metadata.session_month == "Specimen":
        return None
    code = _SESSION_CODE[metadata.session_month]
    year_suffix = str(metadata.session_year)[-2:]
    return (
        f"{metadata.subject_code}_{code}{year_suffix}"
        f"_p{metadata.paper_number}{metadata.paper_variant}"
    )


def raw_to_percentage(raw: dict[str, int | float], max_mark: int | float) -> dict[str, float]:
    """Convert raw mark thresholds to percentages.

    Args:
        raw: Grade → raw mark threshold mapping.
        max_mark: Maximum marks for the paper.

    Returns:
        Grade → percentage threshold mapping.

    Raises:
        ValueError: When max_mark <= 0.
    """
    if max_mark <= 0:
        raise ValueError(f"max_mark must be positive, got {max_mark}")
    return {grade: (mark / max_mark) * 100.0 for grade, mark in raw.items()}


def _percentages(thresholds: dict[str, int], max_mark: int) -> dict[str, float]:
    """Raw marks → percentages.

    Derived at read time, never stored, so every stored number stays one a
    human can check against the PDF.
    """
    return {grade: round((mark / max_mark) * 100.0, 2) for grade, mark in thresholds.items()}


def _load(session: Session) -> _ReferenceTuple:
    """Build the exact/subject-default/global-default maps from verified rows only.

    An unverified row (``verified=False``) is a real transcription whose PDF
    could not be read; ``component_thresholds`` stores it as coverage awaiting
    verification, but nothing may cite Cambridge as its source
    (``lemely/db/models/thresholds.py``). Letting it populate ``exact`` or
    either average would report a guess as ``boundary_source="exact"`` — worse
    than the fallback the chain exists to provide — so unverified rows are
    skipped here entirely. A paper whose only row is unverified falls through
    to the subject/global default instead, which is the intended behaviour.

    ``by_paper`` is keyed ``(subject_code, paper_number)`` rather than just
    ``subject_code`` so the fallback map for a Core paper is built only from
    other Core papers. Grade vocabularies differ by tier at the same subject
    (Core C-G, Extended A*-G) — grouping by subject alone would let an
    Extended paper's A/B boundaries leak into a Core paper's fallback, which a
    Core candidate can never be awarded.
    """
    exact: dict[str, dict[str, float]] = {}
    by_paper: dict[tuple[str, int], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    everything: dict[str, list[float]] = defaultdict(list)
    for row in session.scalars(sa.select(ComponentThreshold)):
        if not row.verified:
            continue
        pct = _percentages(row.thresholds, row.max_mark)
        code = _SESSION_CODE_BY_MONTH[row.session_month]
        year_suffix = row.session_year % 100
        key = f"{row.subject_code}_{code}{year_suffix:02d}_p{row.paper_number}{row.paper_variant}"
        exact[key] = pct
        for grade, value in pct.items():
            by_paper[(row.subject_code, row.paper_number)][grade].append(value)
            everything[grade].append(value)
    subject_defaults = {
        f"{subject}_p{paper_number}": {g: round(mean(v), 2) for g, v in grades.items()}
        for (subject, paper_number), grades in by_paper.items()
    }
    global_default = (
        {g: round(mean(v), 2) for g, v in everything.items()}
        if everything
        else dict(_FALLBACK_GLOBAL)
    )
    return exact, subject_defaults, global_default


def _load_reference(sm: sessionmaker[Session]) -> _ReferenceTuple:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    with sm() as session:
        loaded = _load(session)
    with _lock:
        _cache = loaded
    return loaded


class GradeBoundaryStore:
    """Resolver for CAIE grade boundaries, backed by ``component_thresholds``.

    Fallback chain: exact key → subject default → global default.
    source_tag vocabulary matches GradePrediction.boundary_source Literal values.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self._exact, self._defaults, self._global = _load_reference(self._sessionmaker)

    @property
    def exact_key_count(self) -> int:
        """How many paper variants carry a real, published boundary set.

        X-03 reports this beside the observed ``boundary_source`` distribution:
        the count says how much of the corpus could ever resolve exactly, the
        distribution says how much actually did. Exposed as a property so the
        admin surface does not reach into ``_exact`` (P4.7).
        """
        return len(self._exact)

    @property
    def subject_default_count(self) -> int:
        """How many (subject, paper number) pairs carry a fallback boundary set."""
        return len(self._defaults)

    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
        """Return (boundary_map, source_tag) using the fallback chain.

        source_tag is one of: 'exact', 'subject_default', 'global_default'.
        The subject-default rung is scoped to ``(subject_code, paper_number)``,
        never subject alone, so a Core paper's fallback never contains a grade
        (e.g. "A") sourced entirely from Extended papers of the same subject.
        """
        key = _make_key(metadata)
        if key and key in self._exact:
            return self._exact[key], "exact"

        paper_key = f"{metadata.subject_code}_p{metadata.paper_number}"
        if paper_key in self._defaults:
            return self._defaults[paper_key], "subject_default"

        return self._global, "global_default"
