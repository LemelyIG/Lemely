r"""Det parse coverage over the EXPANDED source corpus. ZERO GEMINI SPEND.

The corpus was extended on 2026-08-29 from 2019-2025 to **2010-2025** for all
three v1 subjects: 479 -> 1,130 canonical mark schemes, 479 -> 1,134 question
papers, downloaded via PaperScraper. No Gemini calls; this is a det-only re-parse.

**Why this measurement and not a claim of improvement.** Every corpus-wide figure
published this session — 331 of 479 exact, 25 collapsed leaves, 8.94% defaulted —
was computed over the 479-scheme population. **Adding 651 schemes changes the
denominator of all of them.** A figure quoted across the two populations would be
comparing different things, so the new population is measured on its own terms
and the old figures are restated as as-of a corpus revision.

The 2010-2018 material is also OLDER, and older CAIE mark schemes use layouts the
parser has never seen. A drop in the exact-reconciliation RATE is therefore the
expected result, not a regression — and it is the point: it is where undiscovered
parser defects live.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/corpus-expanded-2026-08-29"

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
    print(f"{len(schemes)} canonical source mark schemes", flush=True)

    rows = []
    for i, path in enumerate(schemes, 1):
        stem = path.name[:-4]
        year = 2000 + int(stem.split("_")[1][1:]) if len(stem.split("_")) > 1 else None
        rec: dict[str, object] = {
            "scheme": path.name,
            "syllabus": stem.split("_")[0],
            "session_year": year,
            "era": "2019-2025" if (year or 0) >= 19 + 2000 else "2010-2018",
        }
        try:
            sch = DeterministicMarkSchemeParser(cfg)(path)
            lf = [x for r in sch.questions for x in leaves(r)]
            ids = [x.id for x in lf]
            mx = sch.metadata.maximum_mark
            total = sum(x.marks or 0 for x in lf)
            pts = [p for x in lf for p in (x.answer_points or [])]
            rec |= {
                "status": "parsed",
                "maximum_mark": mx,
                "parsed_total": total,
                "exact": bool(mx) and total == mx,
                "n_leaves": len(lf),
                "leaves_lost_to_collapse": len(ids) - len(set(ids)),
                "n_points": len(pts),
                "points_defaulted": sum(1 for p in pts if p.marks_defaulted),
                "alt_points": sum(1 for p in pts if p.is_alternative),
            }
        except Exception as exc:
            rec |= {"status": "error", "error": type(exc).__name__}
        rows.append(rec)
        if i % 100 == 0:
            print(f"  {i}/{len(schemes)}", flush=True)

    ok = [r for r in rows if r.get("status") == "parsed"]
    def agg(subset, key):
        return sum(r.get(key, 0) for r in subset)

    summary: dict[str, object] = {
        "spend_usd": 0.0,
        "gemini_calls": 0,
        "source_schemes": len(rows),
        "parsed": len(ok),
        "errored": len(rows) - len(ok),
        "exact": sum(1 for r in ok if r["exact"]),
        "not_exact": sum(1 for r in ok if not r["exact"]),
        "total_leaves": agg(ok, "n_leaves"),
        "leaves_lost_to_collapse": agg(ok, "leaves_lost_to_collapse"),
        "answer_points": agg(ok, "n_points"),
        "points_defaulted": agg(ok, "points_defaulted"),
        "alt_points": agg(ok, "alt_points"),
        "by_era": {},
        "by_syllabus": {},
    }
    for era in ("2010-2018", "2019-2025"):
        sub = [r for r in ok if r["era"] == era]
        summary["by_era"][era] = {
            "schemes": len(sub),
            "exact": sum(1 for r in sub if r["exact"]),
            "exact_rate": round(sum(1 for r in sub if r["exact"]) / len(sub), 4) if sub else None,
            "leaves": agg(sub, "n_leaves"),
        }
    for syl in sorted({r["syllabus"] for r in ok}):
        sub = [r for r in ok if r["syllabus"] == syl]
        summary["by_syllabus"][syl] = {
            "schemes": len(sub),
            "exact": sum(1 for r in sub if r["exact"]),
            "exact_rate": round(sum(1 for r in sub if r["exact"]) / len(sub), 4),
        }
    summary["error_kinds"] = dict(Counter(r.get("error") for r in rows if r.get("status") == "error"))

    (OUT / "coverage.json").write_text(
        json.dumps({"summary": summary, "per_scheme": rows}, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
