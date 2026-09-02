r"""#112 — corpus-wide before/after for the alternative-marker fix. ZERO SPEND.

Ruling C1 waived the marking sweep on the instrument-blindness ground (the
golden harness reads pre-parsed `mark_scheme.json` and never invokes the det
parser, so both arms would be identical inputs) and put a **zero-spend
deterministic before/after over the corpus** in its place. This is that.

#112 pre-stated its own prediction, which is what makes this falsifiable rather
than decorative: the defect **strictly inflates** `computed_total`, so fixing it
can only ever REDUCE parsed totals — between **77** marks (marker-bearing point
only) and **246** (marker to end of leaf) over #45's 47-paper bucket. A result
outside that band, or in the wrong direction, is a finding about the fix.

Both arms re-parse the same PDFs; the before arm imports a package copy with
`rows.py` taken from `origin/develop`.

Usage:  corpus_before_after.py before|after <package_root>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ARM = sys.argv[1]
sys.path.insert(0, sys.argv[2])

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/alt-routes-112-2026-08-29"

from lemely.io.det.parser import DeterministicMarkSchemeParser  # noqa: E402
from lemely.runtime.config import DetParserSettings  # noqa: E402


def leaves(q):  # type: ignore[no-untyped-def]
    if not q.parts:
        yield q
        return
    for c in q.parts:
        yield from leaves(c)


def main() -> None:
    cfg = DetParserSettings(escalate_on_mark_mismatch=False)
    schemes = sorted(SOURCES.rglob("*_ms_*.pdf"))
    print(f"[{ARM}] {len(schemes)} schemes from {sys.argv[2]}", flush=True)
    rows = []
    for i, path in enumerate(schemes, 1):
        rec: dict[str, object] = {"scheme": path.name}
        try:
            sch = DeterministicMarkSchemeParser(cfg)(path)
            lf = [x for r in sch.questions for x in leaves(r)]
            pts = [p for x in lf for p in (x.answer_points or [])]
            leaf_ids = [x.id for x in lf]
            rec |= {
                "status": "parsed",
                "maximum_mark": sch.metadata.maximum_mark,
                "parsed_total": sum(x.marks or 0 for x in lf),
                "n_leaves": len(lf),
                "n_points": len(pts),
                "n_alternative_points": sum(1 for p in pts if p.is_alternative),
                "leaves_lost_to_collapse": len(leaf_ids) - len(set(leaf_ids)),
                "dup_leaf_ids": len(
                    {k for k, v in Counter(leaf_ids).items() if v > 1}
                ),
            }
        except Exception as exc:
            rec |= {"status": "error", "error": type(exc).__name__}
        rows.append(rec)
        if i % 50 == 0:
            print(f"  [{ARM}] {i}/{len(schemes)}", flush=True)
    (OUT / f"corpus-{ARM}.json").write_text(json.dumps(rows, indent=2) + "\n")
    ok = [r for r in rows if r.get("status") == "parsed"]
    exact = sum(1 for r in ok if r["maximum_mark"] and r["parsed_total"] == r["maximum_mark"])
    print(f"[{ARM}] exact={exact} of {len(rows)}  "
          f"alt_points={sum(r['n_alternative_points'] for r in ok)}", flush=True)


if __name__ == "__main__":
    main()
