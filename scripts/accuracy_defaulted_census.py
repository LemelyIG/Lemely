"""Scratch: count DEFAULTED answer-point marks across the det-parsable corpus.

Zero cost, read-only, no production change. A point is "defaulted" when
rows.make_point receives marks_int=None and mints marks=1 (rows.py:200) --
exactly the provenance #38 says is never recorded. We detect it by wrapping
AnswerPoint and reading the caller frame's marks_int, since the minted point
is indistinguishable from a genuine 1-mark point after construction.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from lemely.core.loose_schemas import AnswerPoint
from lemely.io.det import rows as _rows
from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.config import DetParserSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lemely.core.loose_schemas import Question

_RealAnswerPoint = AnswerPoint
hits: list[dict[str, object]] = []
current: dict[str, str] = {}


def _tracking_answer_point(**kw: object) -> object:
    frame = sys._getframe(1)
    if frame.f_code.co_name == "make_point" and frame.f_locals.get("marks_int") is None:
        point = kw.get("point")
        hits.append(
            {
                "source": current["src"],
                "id": kw.get("id"),
                "point": (point if isinstance(point, str) else "")[:60],
            }
        )
    return _RealAnswerPoint(**kw)


def main(pdfs: list[Path]) -> None:
    # Reconciliation off: we want every paper to parse far enough to count,
    # not to be rejected by the mark-total check we are trying to measure.
    cfg = DetParserSettings(
        escalate_on_mark_mismatch=False,
        escalate_on_defaulted_marks=False,
    )
    parser = DeterministicMarkSchemeParser(cfg)

    parsed = 0
    failed: dict[str, int] = defaultdict(int)
    per_paper: dict[str, int] = {}
    totals: dict[str, tuple[int, int]] = {}

    for pdf in pdfs:
        current["src"] = pdf.name
        before = len(hits)
        try:
            with patch.object(_rows, "AnswerPoint", _tracking_answer_point):
                ms = parser(pdf)
        except Exception as exc:  # census, not a gate: record and carry on
            failed[type(exc).__name__] += 1
            continue
        parsed += 1
        n = len(hits) - before
        if n:
            per_paper[pdf.name] = n
        # Mark impact: phantom marks are exactly the defaulted count, since
        # each mints marks=1 into the primary sum at rows.py:154-158.
        declared = ms.metadata.maximum_mark or 0
        leaf_sum = sum(q.marks for q in _leaves(ms.questions))
        totals[pdf.name] = (declared, leaf_sum)

    print(f"pdfs attempted      : {len(pdfs)}")
    print(f"parsed by det       : {parsed}")
    print(f"det ParseError etc  : {dict(failed)}")
    print(f"papers w/ defaults  : {len(per_paper)} of {parsed}")
    print(f"defaulted points    : {len(hits)}")
    print()
    print("worst papers (defaulted points, declared_max, leaf_sum):")
    for name, n in sorted(per_paper.items(), key=lambda kv: -kv[1])[:15]:
        d, s = totals[name]
        print(f"  {name:28s} {n:4d}   max={d:4}  leaf_sum={s:4}  delta={s - (d or 0):+4}")

    # Is the 1-mark default LOAD-BEARING? On papers whose leaf sum currently
    # reconciles exactly, deleting the minted points (issue #38 bullet 2)
    # would break a total that is right today.
    exact = [nm for nm in per_paper if totals[nm][1] == totals[nm][0] and totals[nm][0]]
    exact_pts = sum(per_paper[nm] for nm in exact)
    print()
    print(f"papers w/ defaults whose leaf_sum == declared max : {len(exact)} of {len(per_paper)}")
    print(f"  defaulted points sitting on those papers        : {exact_pts} of {len(hits)}")
    over = [nm for nm in per_paper if totals[nm][0] and totals[nm][1] > totals[nm][0]]
    under = [nm for nm in per_paper if totals[nm][0] and totals[nm][1] < totals[nm][0]]
    print(f"  over-sum papers  (defaults may be phantom)      : {len(over)}")
    print(f"  under-sum papers (defaults are not the problem) : {len(under)}")

    Path("reports/.scratch/defaulted-census.json").write_text(
        json.dumps(
            {
                "parsed": parsed,
                "defaulted_points": len(hits),
                "per_paper": per_paper,
                "totals": {k: list(v) for k, v in totals.items()},
            },
            indent=1,
        )
    )


def _leaves(questions: list[Question]) -> Iterator[Question]:
    for q in questions:
        if q.parts:
            yield from _leaves(q.parts)
        else:
            yield q


if __name__ == "__main__":
    roots = [Path(a) for a in sys.argv[1:]]
    pdfs: list[Path] = []
    for r in roots:
        pdfs.extend(sorted(r.rglob("*_ms_*.pdf")) if r.is_dir() else [r])
    main(pdfs)
