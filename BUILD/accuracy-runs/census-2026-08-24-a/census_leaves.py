"""Count leaf questions and DA1 strata over a directory of parsed MarkScheme JSON.

DA1 strata (from #57's binding constraints): syllabus code x parse path
(det/Gemini) x tariff band (1 / 2 / 3+ marks). This script only sees schemes
produced by ONE parser, so it reports the parse-path axis as a constant and
leaves the caller to note that the other level is empty.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/sico/Lemely-worktrees/accuracy")

from lemely.core.loose_schemas import MarkScheme  # noqa: E402

out_dir = Path(sys.argv[1])
parse_path = sys.argv[2] if len(sys.argv) > 2 else "det"

leaves_total = 0
papers = 0
bad = []
by_syllabus: Counter[str] = Counter()
by_band: Counter[str] = Counter()
by_stratum: Counter[str] = Counter()
by_syll_paper: Counter[str] = Counter()
roots_total = 0


def band(marks: int) -> str:
    if marks == 1:
        return "1"
    if marks == 2:
        return "2"
    if marks >= 3:
        return "3+"
    return "0/unknown"


for f in sorted(out_dir.glob("*.json")):
    try:
        ms = MarkScheme.model_validate(json.loads(f.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        bad.append((f.name, str(exc)[:120]))
        continue
    papers += 1
    syll = f.name.split("_")[0]
    paper_no = f.name.split("_ms_")[-1].removesuffix(".json")[:1]
    flat = ms.all_questions_flat()
    leaf = [q for q in flat if not getattr(q, "sub_questions", None)]
    roots_total += len(getattr(ms, "questions", []) or [])
    leaves_total += len(leaf)
    by_syllabus[syll] += len(leaf)
    by_syll_paper[f"{syll}p{paper_no}"] += len(leaf)
    for q in leaf:
        b = band(int(getattr(q, "marks", 0) or 0))
        by_band[b] += 1
        by_stratum[f"{syll} x {parse_path} x {b}"] += 1

print(f"parsed schemes loaded : {papers}")
print(f"unloadable JSON       : {len(bad)}")
for name, err in bad[:5]:
    print(f"    ! {name}: {err}")
print(f"root questions        : {roots_total}")
print(f"LEAF questions        : {leaves_total}")
print("\nleaves by syllabus:")
for k, v in sorted(by_syllabus.items()):
    print(f"  {k}: {v}")
print("\nleaves by syllabus x paper:")
for k, v in sorted(by_syll_paper.items()):
    print(f"  {k}: {v}")
print("\nleaves by tariff band:")
for k, v in sorted(by_band.items()):
    print(f"  {k}: {v}")
print(f"\nDA1 strata populated  : {len(by_stratum)} (of 3 syll x 2 path x 3 band = 18)")
for k, v in sorted(by_stratum.items()):
    print(f"  {k}: {v}")
