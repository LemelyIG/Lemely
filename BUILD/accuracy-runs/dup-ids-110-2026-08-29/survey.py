r"""#110 bullet 1 — how widespread are duplicate question ids? ZERO SPEND, det-only.

Leaf identity in this programme is `(paper_id, question_id)` (DA6). A duplicate
`question_id` WITHIN one paper collapses two genuinely different questions into
one leaf — the same narrowed-denominator shape #105 fixed at the analysis layer,
except this one originates in the parser, so correct downstream keying cannot
repair it.

Independent of mark-total reconciliation: a paper can reconcile exactly and
still emit duplicate ids, so `mark_total_mismatch_escalating` does not catch it.
This run reports both, so the overlap is visible rather than assumed.

Run with escalation OFF so a mismatching paper still yields a tree to inspect —
otherwise the survey would only see papers that already reconcile, which is
exactly the selection effect that hid this defect until #95 tripped over it.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/dup-ids-110-2026-08-29"

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
    print(f"{len(schemes)} source schemes", flush=True)

    rows = []
    for i, path in enumerate(schemes, 1):
        rec: dict[str, object] = {"scheme": path.name}
        try:
            sch = DeterministicMarkSchemeParser(cfg)(path)
        except Exception as exc:
            rec |= {"status": "error", "error": type(exc).__name__}
            rows.append(rec)
            continue
        roots = [q.id for q in sch.questions]
        leaf_ids = [lf.id for root in sch.questions for lf in leaves(root)]
        dup_roots = {k: v for k, v in Counter(roots).items() if v > 1}
        dup_leaves = {k: v for k, v in Counter(leaf_ids).items() if v > 1}
        mx = sch.metadata.maximum_mark
        total = sum(lf.marks or 0 for root in sch.questions for lf in leaves(root))
        rec |= {
            "status": "parsed",
            "n_roots": len(roots),
            "n_leaves": len(leaf_ids),
            # leaves LOST to collapsing: the denominator DA6 keying would silently drop
            "leaves_lost_to_collapse": len(leaf_ids) - len(set(leaf_ids)),
            "dup_root_ids": dup_roots,
            "dup_leaf_ids": dup_leaves,
            "reconciles": bool(mx) and total == mx,
        }
        rows.append(rec)
        if i % 50 == 0:
            print(f"  {i}/{len(schemes)}", flush=True)

    parsed = [r for r in rows if r.get("status") == "parsed"]
    with_dups = [r for r in parsed if r["dup_leaf_ids"]]
    recon = [r for r in parsed if r["reconciles"]]
    summary = {
        "issue": 110,
        "spend_usd": 0.0,
        "schemes": len(rows),
        "parsed": len(parsed),
        "errored": len(rows) - len(parsed),
        "schemes_with_duplicate_leaf_ids": len(with_dups),
        "share_of_parsed": round(len(with_dups) / len(parsed), 4) if parsed else None,
        "total_leaves": sum(r["n_leaves"] for r in parsed),
        "total_leaves_lost_to_collapse": sum(r["leaves_lost_to_collapse"] for r in parsed),
        # the point of the issue: reconciling papers are NOT exempt
        "reconciling_schemes": len(recon),
        "reconciling_schemes_WITH_duplicate_ids": sum(1 for r in recon if r["dup_leaf_ids"]),
        "worst_10": sorted(with_dups, key=lambda r: -r["leaves_lost_to_collapse"])[:10],
    }
    (OUT / "survey.json").write_text(
        json.dumps({"summary": summary, "per_scheme": rows}, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2)[:2500])


if __name__ == "__main__":
    main()
