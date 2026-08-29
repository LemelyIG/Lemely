r"""#38 bullets 2-3 / ruling C2 — re-measure the defaulted-mark rate on the FIXED parser.

C2 (human, 2026-08-27): *"Defer behind #136's fix, then re-measure. The 44.4% /
21.6% defaulted rate is contaminated by DA21 mechanism (B); decide the trigger
against a clean rate."*

#136's fix landed (DA34), so the deferral is discharged and this is the clean
rate. **Mechanism (B) was the contamination**: where the marks column merged into
the answer cell, the code arrived as trailing text, `parse_marks_cell` saw
nothing, and every such point defaulted. Those codes are now recovered and are
no longer flagged `marks_defaulted`, because a mark read from the wrong column
was still READ, not minted.

Both arms over the SAME schemes; the before arm imports a package copy with
`rows.py`/`marks.py` from the pre-#136 revision. ZERO SPEND, det-only.

Usage:  measure.py <arm> <package_root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ARM = sys.argv[1]
sys.path.insert(0, sys.argv[2])

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/defaulted-38-2026-08-29"

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
    print(f"[{ARM}] {len(schemes)} schemes", flush=True)

    papers = 0
    papers_any_defaulted = 0
    papers_all_defaulted = 0
    points = 0
    points_defaulted = 0
    per: list[dict[str, object]] = []

    for i, path in enumerate(schemes, 1):
        try:
            sch = DeterministicMarkSchemeParser(cfg)(path)
        except Exception:
            continue
        pts = [p for r in sch.questions for lf in leaves(r) for p in (lf.answer_points or [])]
        if not pts:
            continue
        papers += 1
        n_def = sum(1 for p in pts if p.marks_defaulted)
        points += len(pts)
        points_defaulted += n_def
        if n_def:
            papers_any_defaulted += 1
        if n_def == len(pts):
            papers_all_defaulted += 1
        per.append({"scheme": path.name, "points": len(pts), "defaulted": n_def})
        if i % 100 == 0:
            print(f"  [{ARM}] {i}/{len(schemes)}", flush=True)

    summary = {
        "arm": ARM,
        "spend_usd": 0.0,
        "papers_with_points": papers,
        "papers_with_any_defaulted": papers_any_defaulted,
        "papers_all_defaulted": papers_all_defaulted,
        "answer_points": points,
        "points_defaulted": points_defaulted,
        "pct_papers_any_defaulted": round(papers_any_defaulted / papers, 4) if papers else None,
        "pct_points_defaulted": round(points_defaulted / points, 4) if points else None,
    }
    (OUT / f"{ARM}.json").write_text(json.dumps({"summary": summary, "per_scheme": per}, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
