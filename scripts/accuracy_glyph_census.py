"""Scratch-grade corpus census for #39 (M1.4) detector bullets. Zero cost.

Measures, over the det-parsed corpus, the three things #39's acceptance bullets
5/6/7 assert without ever having been checked at scale:

* private-use codepoints (U+E000-U+F8FF) in answer-point text -- bullet 6 says
  "all 6 instances live" on the det path;
* the fraction-bar shape -- expression, newline, expression, with no operator
  at the boundary -- bullet 5;
* raw newline incidence -- bullet 7 warns a raw newline count is NOT a usable
  detector ("272 of 1,000 det points contain newlines, many legitimately").

The issue's own figures come from 33 schemes / 575 questions. This runs the
same questions over every scheme the det parser can read, so bullet 9's
"zero false positives" requirement can be judged against a real denominator.

The fraction-bar rule here is a deliberately CONSERVATIVE PROXY, not the
production detector: it fires only when both sides of a newline are bare
numeric expressions. Report it as a lower bound.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.config import DetParserSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lemely.core.loose_schemas import MarkScheme, Question

# Unicode private-use area. Glyphs here render as .notdef / garbage and carry no
# stable meaning -- their presence means the PDF's font encoding was not resolved.
_PUA = re.compile("[\ue000-\uf8ff]")

# A bare numeric expression: digits, optional decimal, optional leading sign,
# optionally wrapped in the units/parenthetical noise CAIE schemes carry.
_NUMERIC = re.compile(r"^[\s(]*[-+]?\d[\d\s.,x*^/eE+-]*[\s)]*$")

# An operator sitting at either edge of the split would explain the newline
# without a fraction bar being involved.
_EDGE_OP = re.compile(r"[-+*/=x]\s*$|^\s*[-+*/=]")


def _leaves(questions: list[Question]) -> Iterator[Question]:
    for q in questions:
        if q.parts:
            yield from _leaves(q.parts)
        else:
            yield q


def _naive_fraction_bar(text: str) -> bool:
    """The rule #39 bullet 5 states literally: numeric line, newline, numeric line.

    Kept alongside the strict rule so the two can be compared. This one fires on
    any ADJACENT numeric pair anywhere in the text, which is what makes it match
    truth tables and stem-and-leaf blocks -- the gap between this count and
    ``_classify``'s is the false-positive budget bullet 9 has to survive.
    """
    if "\n" not in text:
        return False
    segs = text.split("\n")
    for before, after in pairwise(segs):
        if not before.strip() or not after.strip():
            continue
        if _EDGE_OP.search(before) or _EDGE_OP.search(after):
            continue
        if _NUMERIC.match(before) and _NUMERIC.match(after):
            return True
    return False


def _classify(text: str) -> str | None:
    """Return 'fraction' | 'table' | None for a newline-joined numeric shape.

    The naive rule -- "numeric line, newline, numeric line" -- fires on TRUTH
    TABLES and other tabular data as readily as on a linearised fraction bar.
    Observed immediately on 0625_s19_ms_43, whose logic-gate truth tables match
    it exactly. Bullet 7 warns about precisely this class (coordinate lists,
    stem-and-leaf, matrices), so the two are separated here rather than summed:
    a fraction has exactly TWO numeric segments (numerator over denominator);
    three or more stacked numeric rows is a table.
    """
    if "\n" not in text:
        return None
    segs = [s for s in text.split("\n") if s.strip()]
    numeric = [s for s in segs if _NUMERIC.match(s) and not _EDGE_OP.search(s)]
    if len(numeric) < 2 or len(numeric) != len(segs):
        return None
    return "fraction" if len(numeric) == 2 else "table"


def main(pdfs: list[Path]) -> None:
    cfg = DetParserSettings(
        escalate_on_mark_mismatch=False,
        escalate_on_defaulted_marks=False,
    )
    parser = DeterministicMarkSchemeParser(cfg)

    points = 0
    with_newline = 0
    pua_points = 0
    pua_papers: Counter[str] = Counter()
    pua_chars: Counter[str] = Counter()
    frac_points = 0
    frac_papers: Counter[str] = Counter()
    frac_examples: list[dict[str, str]] = []
    table_points = 0
    table_examples: list[dict[str, str]] = []
    naive_points = 0
    naive_only_examples: list[dict[str, str]] = []
    parsed = 0
    failed: Counter[str] = Counter()

    for pdf in pdfs:
        try:
            ms: MarkScheme = parser(pdf)
        except Exception as exc:  # census, not a gate: record and carry on
            failed[type(exc).__name__] += 1
            continue
        parsed += 1
        for q in _leaves(ms.questions):
            for p in q.answer_points or []:
                text = p.point or ""
                points += 1
                if "\n" in text:
                    with_newline += 1
                found = _PUA.findall(text)
                if found:
                    pua_points += 1
                    pua_papers[pdf.name] += 1
                    for ch in found:
                        pua_chars[f"U+{ord(ch):04X}"] += 1
                kind = _classify(text)
                if _naive_fraction_bar(text):
                    naive_points += 1
                    if kind != "fraction" and len(naive_only_examples) < 10:
                        naive_only_examples.append(
                            {"source": pdf.name, "id": p.id or "?", "text": text[:80]}
                        )
                if kind == "fraction":
                    frac_points += 1
                    frac_papers[pdf.name] += 1
                    if len(frac_examples) < 12:
                        frac_examples.append(
                            {"source": pdf.name, "id": p.id or "?", "text": text[:80]}
                        )
                elif kind == "table":
                    table_points += 1
                    if len(table_examples) < 8:
                        table_examples.append(
                            {"source": pdf.name, "id": p.id or "?", "text": text[:80]}
                        )

    pct = (100.0 * with_newline / points) if points else 0.0
    print(f"schemes attempted        : {len(pdfs)}")
    print(f"schemes parsed by det    : {parsed}   failures={dict(failed)}")
    print(f"answer points examined   : {points}")
    print()
    print(f"points containing \\n     : {with_newline}  ({pct:.1f}%)  <- bullet 7: NOT a detector")
    print(f"private-use-codepoint pts: {pua_points}  across {len(pua_papers)} schemes")
    print(f"  codepoints seen        : {dict(pua_chars.most_common(10))}")
    print(f"  worst schemes          : {dict(pua_papers.most_common(8))}")
    print()
    print(
        f"fraction-bar shape (proxy, LOWER BOUND): {frac_points} pts "
        f"across {len(frac_papers)} schemes"
    )
    for ex in frac_examples[:8]:
        print(f"  {ex['source']:24s} {ex['id']:6s} {ex['text']!r}")
    print()
    print(
        f"all-numeric TABULAR blocks (3+ stacked rows): {table_points} pts "
        f"-- bullet 7's false-positive class, NOT fraction bars"
    )
    for ex in table_examples[:6]:
        print(f"  {ex['source']:24s} {ex['id']:6s} {ex['text']!r}")
    print()
    over = naive_points - frac_points
    ratio = f"{over / frac_points:.1f}x" if frac_points else "n/a"
    print(f"BULLET 5 AS LITERALLY STATED (naive adjacent pair): {naive_points} pts")
    print(f"  over-fires vs the strict rule by {over} pts ({ratio}) <- bullet 9 must survive these")
    for ex in naive_only_examples[:6]:
        print(f"  FP {ex['source']:22s} {ex['id']:6s} {ex['text']!r}")

    Path("reports/.scratch/glyph-census.json").write_text(
        json.dumps(
            {
                "schemes_parsed": parsed,
                "points": points,
                "points_with_newline": with_newline,
                "pua_points": pua_points,
                "pua_papers": dict(pua_papers),
                "pua_chars": dict(pua_chars),
                "fraction_bar_points": frac_points,
                "fraction_bar_papers": dict(frac_papers),
                "fraction_bar_examples": frac_examples,
                "tabular_false_positive_points": table_points,
                "tabular_false_positive_examples": table_examples,
                "naive_bullet5_points": naive_points,
                "naive_only_examples": naive_only_examples,
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    roots = [Path(a) for a in sys.argv[1:]]
    found_pdfs: list[Path] = []
    for r in roots:
        found_pdfs.extend(sorted(r.rglob("*_ms_*.pdf")) if r.is_dir() else [r])
    main(found_pdfs)
