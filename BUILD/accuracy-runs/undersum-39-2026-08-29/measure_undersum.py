"""#39 bullet 2 — how many questions UNDER-sum? Measure before gating. ZERO SPEND.

`Question.validate_mark_point_sum` is one-sided: it raises only when primary
points EXCEED the tariff. #39 asks for the under-sum direction to be checked
too. Before adding a check, measure how often it would fire — the same order of
operations #38's `escalate_on_defaulted_marks` got wrong, where a plausible gate
turned out to fire on 44.4% of papers.
"""
import sys, json
sys.path.insert(0,"/home/sico/Lemely-worktrees/accuracy")
from pathlib import Path
from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.config import DetParserSettings
from lemely.core.loose_schemas import QuestionType
SRC=Path("/home/sico/PaperScraper/papers")
cfg=DetParserSettings(escalate_on_mark_mismatch=False)
EXEMPT={QuestionType.LEVELS_BASED,QuestionType.INDICATIVE_CONTENT,QuestionType.MCQ}
def leaves(q):
    if not q.parts: yield q; return
    for c in q.parts: yield from leaves(c)
schemes=sorted(SRC.rglob("*_ms_*.pdf"))
tot=under=over=exact_=nopts=0
sch_under=set(); worst=[]
for i,p in enumerate(schemes,1):
    try: s=DeterministicMarkSchemeParser(cfg)(p)
    except Exception: continue
    for r in s.questions:
        for lf in leaves(r):
            if lf.type in EXEMPT: continue
            pts=lf.answer_points or []
            if not pts: nopts+=1; continue
            tot+=1
            prim=sum(x.marks or 0 for x in pts if not x.is_alternative and not getattr(x,"is_optional",False))
            m=lf.marks or 0
            if m<=0: continue
            if prim<m:
                under+=1; sch_under.add(p.name); worst.append((p.name,lf.id,m,prim))
            elif prim>m: over+=1
            else: exact_+=1
    if i%100==0: print(f"  {i}/{len(schemes)}",flush=True)
out={"questions_with_points":tot,"exact":exact_,"under_sum":under,"over_sum":over,
     "questions_with_NO_points":nopts,
     "under_rate":round(under/tot,4) if tot else None,
     "schemes_with_any_under_sum":len(sch_under),
     "worst_10":sorted(worst,key=lambda x:x[2]-x[3],reverse=True)[:10]}
Path("/tmp/undersum.json").write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
