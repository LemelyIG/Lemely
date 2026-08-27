"""Count leaf questions and DA1 strata over a directory of parsed MarkScheme JSON.

DA1 strata (from #57's binding constraints): syllabus code x parse path
(det/Gemini) x tariff band (1 / 2 / 3+ marks). This script only sees schemes
produced by ONE parser, so it reports the parse-path axis as a constant and
leaves the caller to note that the other level is empty.

CORRECTED 2026-08-25 (#88 item 3, ratified by the human). The original version
filtered leaves on ``getattr(q, "sub_questions", None)``. ``Question`` has no
such field -- its child list is ``parts`` (loose_schemas.py:1008) -- so the
filter was a NO-OP and every printed "LEAF questions" figure was really
*every question at every depth*. That is the whole of the "12,358 leaves" and
"2,894 unbanded leaves" story: the 2,894 were the 2,894 PARENT questions,
which correctly carry no tariff because their marks live in their children.
The corrected run prints both totals side by side so the two can never be
confused again, and the strata count now excludes the ``0/unknown``
catch-all, which is what produced the discredited "populated: 12".

The original (buggy) output is preserved verbatim at ``census-leaves.txt``;
the corrected output of this script is ``census-leaves-corrected.txt``.
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
flat_total = 0
parents_total = 0
parents_with_own_marks = 0
unbanded_leaves = 0
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
    # `parts` is the child list; there is no `sub_questions` field (see module docstring).
    leaf = [q for q in flat if not q.parts]
    parents = [q for q in flat if q.parts]
    roots_total += len(getattr(ms, "questions", []) or [])
    flat_total += len(flat)
    parents_total += len(parents)
    parents_with_own_marks += sum(1 for q in parents if int(getattr(q, "marks", 0) or 0) > 0)
    leaves_total += len(leaf)
    by_syllabus[syll] += len(leaf)
    by_syll_paper[f"{syll}p{paper_no}"] += len(leaf)
    for q in leaf:
        b = band(int(getattr(q, "marks", 0) or 0))
        by_band[b] += 1
        if b == "0/unknown":
            unbanded_leaves += 1
            continue  # not a DA1 stratum -- never counted as one
        by_stratum[f"{syll} x {parse_path} x {b}"] += 1

print(f"parsed schemes loaded : {papers}")
print(f"unloadable JSON       : {len(bad)}")
for name, err in bad[:5]:
    print(f"    ! {name}: {err}")
print(f"root questions        : {roots_total}")
print(f"ALL questions (flat)  : {flat_total}   <- NOT the leaf corpus")
print(f"  of which PARENTS    : {parents_total}   (carry no tariff; marks live in children)")
print(f"  parents w/ own marks: {parents_with_own_marks}")
print(f"LEAF questions        : {leaves_total}   <- the honest denominator")
print(f"UNBANDED true leaves  : {unbanded_leaves}")
print("\nleaves by syllabus:")
for k, v in sorted(by_syllabus.items()):
    print(f"  {k}: {v}")
print("\nleaves by syllabus x paper:")
for k, v in sorted(by_syll_paper.items()):
    print(f"  {k}: {v}")
print("\nleaves by tariff band:")
for k, v in sorted(by_band.items()):
    print(f"  {k}: {v}")
print(
    f"\nDA1 strata populated  : {len(by_stratum)} (of 3 syll x 2 path x 3 band = 18)"
    "   -- the 0/unknown catch-all is NOT a band and is excluded"
)
for k, v in sorted(by_stratum.items()):
    print(f"  {k}: {v}")
