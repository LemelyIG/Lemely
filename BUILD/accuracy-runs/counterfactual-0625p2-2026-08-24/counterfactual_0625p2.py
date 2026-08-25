"""Counterfactual reparse: do the 40 0625 p2 schemes actually parse as MCQ?

The #45 census labels them `paper_profile_misconfiguration` on a DEMONSTRATED
BRANCH DIFFERENCE, explicitly "not an attempted counterfactual reparse". This
supplies exactly that missing evidence. Read-only; no network; no spend.
"""
from __future__ import annotations
import sys, traceback
from pathlib import Path

from lemely.core.loose_schemas import PaperType
from lemely.io.det import profiles
from lemely.io.det.parser import DeterministicMarkSchemeParser
from lemely.runtime.errors import ParseError

CORPUS = Path("/home/sico/PaperScraper/papers")
ROWS = Path("BUILD/accuracy-runs/census-2026-08-24-b/classified-failures.txt")

stems = [l.split()[0] for l in ROWS.read_text().splitlines()
         if "paper_profile_misconfiguration" in l]
print(f"stems labelled paper_profile_misconfiguration: {len(stems)}")

def run(label: str) -> dict[str, int]:
    parser = DeterministicMarkSchemeParser()
    ok = fail = missing = 0
    reasons: dict[str, int] = {}
    for stem in stems:
        m = list(CORPUS.rglob(f"{stem}.pdf"))
        if not m:
            missing += 1; continue
        try:
            parser(m[0]); ok += 1
        except ParseError as e:
            fail += 1
            k = str(e).split("(")[0][:60]
            reasons[k] = reasons.get(k, 0) + 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            reasons[f"{type(e).__name__}"] = reasons.get(type(e).__name__, 0) + 1
    print(f"\n[{label}] parsed_ok={ok}  failed={fail}  missing={missing}")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:6]:
        print(f"    {v:3d}  {k}")
    return {"ok": ok, "fail": fail, "missing": missing}

before = run("AS SHIPPED  (paper 2 -> THEORY_CORE)")
profiles._PHYSICS_PROFILE.paper_type_by_number[2] = PaperType.MCQ
after = run("COUNTERFACTUAL (paper 2 -> MCQ)")

print("\n==== VERDICT ====")
print(f"as shipped     : {before['ok']}/{len(stems)} parse")
print(f"counterfactual : {after['ok']}/{len(stems)} parse")
print(f"schemes moved from FAIL to PASS by the profiles.py:50 fix: {after['ok'] - before['ok']}")
