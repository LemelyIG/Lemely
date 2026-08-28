r"""#136 — corpus-wide before/after, det-only, ZERO SPEND.

The four blocking schemes were the acceptance criteria; this asks the question
the FINDINGS deliberately left open: **how many of every source mark scheme
available locally now reconcile with their printed maximum, and how many did
before?**

It has to RE-PARSE PDFs. The committed `mark_scheme.json` is the post-loss
artefact and cannot show marks that never became answer points — reading it
would measure the bug's output rather than the bug.

The "before" arm imports a copy of the package with `rows.py`/`marks.py` taken
from `origin/develop`, so both arms run the same harness over the same PDFs and
the only difference is the diff under test.

Usage:  corpus_before_after.py before|after <package_root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ARM = sys.argv[1]
PKG = Path(sys.argv[2])
sys.path.insert(0, str(PKG))

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/det-fix-136-2026-08-28"

from lemely.io.det.parser import DeterministicMarkSchemeParser  # noqa: E402
from lemely.runtime.config import DetParserSettings  # noqa: E402


def leaves_of(q):  # type: ignore[no-untyped-def]
    if not q.parts:
        yield q
        return
    for child in q.parts:
        yield from leaves_of(child)


def main() -> None:
    # escalate_on_mark_mismatch=False so a mismatching scheme still REPORTS its
    # total instead of raising — the point is to count mismatches, not hit them.
    cfg = DetParserSettings(escalate_on_mark_mismatch=False)
    schemes = sorted(SOURCES.rglob("*_ms_*.pdf"))
    print(f"[{ARM}] {len(schemes)} source schemes from {PKG}", flush=True)

    rows = []
    for i, path in enumerate(schemes, 1):
        rec: dict[str, object] = {"scheme": path.name}
        try:
            scheme = DeterministicMarkSchemeParser(cfg)(path)
            leaves = [lf for root in scheme.questions for lf in leaves_of(root)]
            mx = scheme.metadata.maximum_mark
            rec |= {
                "status": "parsed",
                "maximum_mark": mx,
                "parsed_total": sum(lf.marks or 0 for lf in leaves),
                "paper_type": getattr(scheme.metadata.paper_type, "value", None),
            }
        except Exception as exc:
            rec |= {"status": "error", "error": type(exc).__name__}
        rows.append(rec)
        if i % 50 == 0:
            print(f"  [{ARM}] {i}/{len(schemes)}", flush=True)

    (OUT / f"corpus-{ARM}.json").write_text(json.dumps(rows, indent=2) + "\n")
    exact = sum(
        1 for r in rows
        if r.get("status") == "parsed" and r.get("maximum_mark") and r["parsed_total"] == r["maximum_mark"]
    )
    print(f"[{ARM}] exact={exact} of {len(rows)}", flush=True)


if __name__ == "__main__":
    main()
