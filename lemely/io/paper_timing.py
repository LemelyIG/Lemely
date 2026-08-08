"""Loader for the bundled CAIE paper timing facts (P4.4, D4.6 §5).

Mirrors :mod:`lemely.io.syllabus_topics`: bundled static JSON, no network
calls, keyed on ``(board, subject_code)`` so Edexcel and Oxford AQA arrive as
extra entries rather than a schema change.

The file stores only ``duration_minutes`` and ``total_marks``, both
transcribed from the syllabus's Assessment overview. The minutes-per-mark rate
a placement estimate needs is *computed* from those two
(:attr:`~lemely.core.placement.PaperTiming.minutes_per_mark`) and never
written down — so every number on disk is one a human can check against the
source document, and there is no derived figure to drift out of step with it.
"""

from __future__ import annotations

import json
from functools import lru_cache

from lemely.core.placement import PaperTiming
from lemely.data import DATA_DIR

_TIMING_PATH = DATA_DIR / "paper_timing.json"


@lru_cache(maxsize=1)
def load_paper_timings() -> dict[tuple[str, str], dict[int, PaperTiming]]:
    """Return every bundled timing, keyed ``(board, subject_code)`` → ``paper_number``.

    Cached: the file is static and placement assembly consults it once per
    candidate question.
    """
    payload = json.loads(_TIMING_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], dict[int, PaperTiming]] = {}
    for raw in payload["papers"]:
        timing = PaperTiming(
            board=raw["board"],
            subject_code=raw["subject_code"],
            paper_number=int(raw["paper_number"]),
            duration_minutes=int(raw["duration_minutes"]),
            total_marks=int(raw["total_marks"]),
            practical=bool(raw["practical"]),
            source_document=raw["source"]["document"],
            syllabus_version=raw["source"]["syllabus_version"],
        )
        out.setdefault((timing.board, timing.subject_code), {})[timing.paper_number] = timing
    return out


def get_paper_timings(
    subject_code: str, *, board: str = "caie", include_practical: bool = False
) -> dict[int, PaperTiming]:
    """Timings for one subject, keyed by paper number.

    An empty mapping is a normal outcome, not an error: a subject we have not
    transcribed an Assessment overview for yet has no eligible placement
    questions, which is what the caller should report.

    Practical papers (0625 Paper 5/6) are **excluded by default**. Their
    questions assume apparatus in front of the candidate, so a practical
    question in an at-home 15-minute placement test measures whether the
    student has a ripple tank, not what they know. The timings are still
    transcribed and available — this is a placement-assembly policy, not a
    claim that the data is wrong.
    """
    timings = load_paper_timings().get((board, subject_code), {})
    if include_practical:
        return dict(timings)
    return {number: t for number, t in timings.items() if not t.practical}
