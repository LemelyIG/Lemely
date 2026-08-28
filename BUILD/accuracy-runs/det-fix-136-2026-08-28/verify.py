r"""#136 — before/after over the four blocking schemes AND the whole corpus.

Det-only, read-only, ZERO SPEND. Two questions:

1. Do the four schemes that block #95 now parse? Each is reported with its
   printed maximum and its parsed total, so a paper that still fails is a
   STATED LIMIT rather than a silent omission.
2. What is the prevalence across every source scheme available locally? The
   FINDINGS for the two 0625 papers named both mechanisms on n=2 and said
   prevalence was UNMEASURED. This measures it — and it has to re-parse PDFs,
   because the committed JSON is the POST-loss artefact and cannot show marks
   that never became answer points.

Run with `escalate_on_mark_mismatch=False` so a failing tree still reports its
total instead of raising.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))
SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD/accuracy-runs/det-fix-136-2026-08-28"

from lemely.io.det.parser import DeterministicMarkSchemeParser  # noqa: E402
from lemely.runtime.config import DetParserSettings  # noqa: E402

BLOCKING = [
    "0580_s23_ms_22.pdf",
    "0606_s23_ms_12.pdf",
    "0625_s20_ms_31.pdf",
    "0625_w21_ms_32.pdf",
]


def leaves_of(q):  # type: ignore[no-untyped-def]
    if not q.parts:
        yield q
        return
    for child in q.parts:
        yield from leaves_of(child)


def totals(path: Path, cfg: DetParserSettings) -> tuple[int, int] | None:
    try:
        scheme = DeterministicMarkSchemeParser(cfg)(path)
    except Exception:
        return None
    leaves = [leaf for root in scheme.questions for leaf in leaves_of(root)]
    return scheme.metadata.maximum_mark or 0, sum(leaf.marks or 0 for leaf in leaves)


def main() -> None:
    cfg = DetParserSettings(escalate_on_mark_mismatch=False)
    which = sys.argv[1] if len(sys.argv) > 1 else "blocking"

    if which == "blocking":
        rows = []
        for name in BLOCKING:
            path = next(SOURCES.rglob(name))
            got = totals(path, cfg)
            if got is None:
                rows.append({"scheme": name, "status": "PARSE_ERROR"})
                continue
            mx, parsed = got
            rows.append(
                {
                    "scheme": name,
                    "maximum_mark": mx,
                    "parsed_total": parsed,
                    "delta": parsed - mx,
                    "status": "EXACT" if parsed == mx else "STILL_MISMATCHED",
                }
            )
            print(f"{name:24s} max={mx:4d} parsed={parsed:4d} delta={parsed - mx:+4d} {rows[-1]['status']}")
        (OUT / "blocking.json").write_text(json.dumps(rows, indent=2) + "\n")
        return

    # Corpus prevalence: every mark-scheme PDF available locally.
    schemes = sorted(SOURCES.rglob("*_ms_*.pdf"))
    print(f"{len(schemes)} source schemes", flush=True)
    out = []
    for i, path in enumerate(schemes, 1):
        got = totals(path, cfg)
        out.append(
            {"scheme": path.name, "ok": got is not None,
             "maximum_mark": got[0] if got else None,
             "parsed_total": got[1] if got else None}
        )
        if i % 25 == 0:
            print(f"  {i}/{len(schemes)}", flush=True)
    (OUT / f"corpus-{sys.argv[2]}.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
