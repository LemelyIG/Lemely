"""#136: narrow the two 0625 mark-total deficits. Det-only, $0.00, read-only.

B4 recorded these as **UNRESOLVED, not diagnosed** and named the falsified
`rows.py` `flush()`/`q_row_had_answer` lead so it would not be re-derived. This
probe rules out three more places the loss is NOT, and localises where it is.

Run with `escalate_on_mark_mismatch=False` so the tree survives inspection.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

import pdfplumber  # noqa: E402

from lemely.io.det.marks import parse_marks_cell  # noqa: E402
from lemely.io.det.parser import DeterministicMarkSchemeParser  # noqa: E402
from lemely.io.det.tables import qualifies_as_mark_scheme_table, select_tables  # noqa: E402
from lemely.runtime.config import DetParserSettings  # noqa: E402

PAPERS = ("0625_s20_ms_31.pdf", "0625_w21_ms_32.pdf")
SOURCES = Path("/home/sico/PaperScraper/papers")


def leaves_of(question):  # type: ignore[no-untyped-def]
    kids = question.parts or []
    if not kids:
        yield question
    for k in kids:
        yield from leaves_of(k)


def main() -> None:
    cfg = DetParserSettings(escalate_on_mark_mismatch=False)
    for name in PAPERS:
        path = next(SOURCES.rglob(name))
        scheme = DeterministicMarkSchemeParser(cfg)(path)
        leaves = [leaf for root in scheme.questions for leaf in leaves_of(root)]
        total = sum(leaf.marks or 0 for leaf in leaves)

        print(f"=== {name}: max={scheme.metadata.maximum_mark} parsed={total} "
              f"deficit={scheme.metadata.maximum_mark - total}")
        print(f"    roots={len(scheme.questions)} leaves={len(leaves)}")

        # (1) Table selection — is any mark-scheme table being dropped?
        with pdfplumber.open(path) as pdf:
            kept = select_tables(pdf, 2, cfg.max_mark_per_point)
            dropped = []
            for page_no, page in enumerate(pdf.pages):
                if page_no < 2:
                    continue
                for tbl in page.extract_tables():
                    if not qualifies_as_mark_scheme_table(tbl, cfg.max_mark_per_point):
                        head = " ".join((c or "")[:24] for c in (tbl[0] or [])[:2])
                        dropped.append(f"p{page_no} rows={len(tbl)} {head!r}")
        print(f"    kept_tables={len(kept)} dropped_tables={len(dropped)}")
        for d in dropped:
            print(f"      dropped: {d}")

        # (2) Mark-cell notation — does anything in the marks column fail to parse?
        codes: collections.Counter[str] = collections.Counter()
        unparsed: collections.Counter[str] = collections.Counter()
        for tbl in kept:
            for row in tbl:
                if not row:
                    continue
                cell = (row[-1] or "").strip().replace("\n", " ")
                if not cell or cell.lower() == "marks":
                    continue
                codes[cell] += 1
                if parse_marks_cell(cell, cfg.max_mark_per_point) is None:
                    unparsed[cell] += 1
        print(f"    distinct_marks_cells={len(codes)} unparsed={dict(unparsed)}")

        # (3) Propagation — leaf.marks vs its own answer points, and empty leaves.
        zero = [leaf.id for leaf in leaves if not leaf.marks]
        pointless = [leaf.id for leaf in leaves if not (leaf.answer_points or [])]
        mismatched = [
            (leaf.id, leaf.marks, sum(p.marks or 0 for p in leaf.answer_points))
            for leaf in leaves
            if (leaf.answer_points or [])
            and sum(p.marks or 0 for p in leaf.answer_points) != (leaf.marks or 0)
        ]
        print(f"    zero_mark_leaves={zero} leaves_without_points={pointless}")
        print(f"    leaf_vs_points_mismatches={mismatched}")


if __name__ == "__main__":
    main()
