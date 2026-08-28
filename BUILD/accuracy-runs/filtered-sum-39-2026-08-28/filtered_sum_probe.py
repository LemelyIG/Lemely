"""#39 bullet 1: how does the FILTERED-sum invariant stand after #136's (D)?

#39 measured 67 raw mismatches of 575 det questions across 6 schemes, and 0
under the filtered sum. Mechanism (D) now sets is_alternative=True on
bracketed points, which is the SAME filter that bullet's invariant names — so
both figures move, and the tautology argument needs re-checking rather than
inheriting.
"""
import sys
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.config import DetParserSettings

cfg = DetParserSettings(escalate_on_mark_mismatch=False)
SRC = Path("/home/sico/PaperScraper/papers")
names = [p.name for p in sorted(SRC.rglob("*_ms_*.pdf"))][: int(sys.argv[1])]

def leaves(q):
    if not q.parts:
        yield q; return
    for c in q.parts: yield from leaves(c)

raw_bad = filt_bad = qs = alt_pts = tot_pts = 0
raw_schemes, filt_schemes = set(), set()
for n in names:
    try: sch = DeterministicMarkSchemeParser(cfg)(next(SRC.rglob(n)))
    except Exception: continue
    for root in sch.questions:
        for lf in leaves(root):
            pts = lf.answer_points or []
            if not pts: continue
            qs += 1; tot_pts += len(pts)
            alt_pts += sum(1 for p in pts if p.is_alternative)
            raw = sum(p.marks or 0 for p in pts)
            flt = sum(p.marks or 0 for p in pts if not p.is_alternative and not getattr(p, "is_optional", False))
            if raw != (lf.marks or 0): raw_bad += 1; raw_schemes.add(n)
            if flt != (lf.marks or 0): filt_bad += 1; filt_schemes.add(n)
print(f"schemes={len(names)} questions_with_points={qs} points={tot_pts} alternative_points={alt_pts}")
print(f"raw-sum mismatches   {raw_bad} across {len(raw_schemes)} schemes")
print(f"filtered-sum mismatch {filt_bad} across {len(filt_schemes)} schemes")
