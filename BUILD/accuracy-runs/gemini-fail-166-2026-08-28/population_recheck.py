"""#166 preflight, step 1: has #136 already changed the population? ZERO SPEND."""
import sys
sys.path.insert(0,"/home/sico/Lemely-worktrees/accuracy")
from pathlib import Path
from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.config import DetParserSettings
SRC=Path("/home/sico/PaperScraper/papers")
STEMS=["0606_m20_ms_12","0606_m21_ms_22","0606_s23_ms_11","0606_w19_ms_22",
       "0580_s21_ms_23","0580_s23_ms_41","0625_m20_ms_32","0625_s19_ms_53",
       "0625_s23_ms_41","0625_s25_ms_42","0625_w19_ms_52","0625_w19_ms_61"]
def leaves(q):
    if not q.parts: yield q; return
    for c in q.parts: yield from leaves(c)
# DEFAULT config — escalation ON, which is what decides "det fails outright"
cfg=DetParserSettings()
for s in STEMS:
    try:
        p=next(SRC.rglob(s+".pdf"))
    except StopIteration:
        print(f"{s:20s} NO LOCAL PDF"); continue
    try:
        sch=DeterministicMarkSchemeParser(cfg)(p)
        tot=sum(l.marks or 0 for r in sch.questions for l in leaves(r))
        print(f"{s:20s} DET NOW PARSES  {tot}/{sch.metadata.maximum_mark}")
    except Exception as e:
        print(f"{s:20s} det fails: {type(e).__name__}: {str(e)[:70]}")
