"""Enumerate the det-parser failure set over the restored mark-scheme corpus.

The failure set is derived by SET DIFFERENCE — every ``*_ms_*.pdf`` the corpus
holds, minus every ``*.json`` the det run actually produced — rather than by
parsing the run log. Log-derived counts only see failure modes that happen to
emit an event; the set difference sees every scheme that did not produce a
scheme, whatever the reason.

Emits the count, the breakdown by syllabus x paper, and (when a log is given)
the observed reason for each failure where one was logged.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

corpus_root = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
log_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

pdfs = {p.stem for p in corpus_root.rglob("*_ms_*.pdf")}
produced = {p.stem for p in out_dir.glob("*.json")}
failed = sorted(pdfs - produced)

print(f"mark-scheme PDFs in corpus : {len(pdfs)}")
print(f"schemes produced by det    : {len(produced)}")
print(f"DET FAILURE SET            : {len(failed)}")
if pdfs:
    print(f"det success rate           : {len(produced) / len(pdfs):.1%}")

by_sp: Counter[str] = Counter()
by_syll: Counter[str] = Counter()
for stem in failed:
    m = re.match(r"(\d{4})_([a-z]\d{2})_ms_(\d)(\d*)", stem)
    if not m:
        by_sp["unparseable-name"] += 1
        continue
    by_syll[m.group(1)] += 1
    by_sp[f"{m.group(1)} p{m.group(3)}"] += 1

print("\nfailures by syllabus:")
for k, v in sorted(by_syll.items()):
    print(f"  {k}: {v}")
print("\nfailures by syllabus x paper:")
for k, v in sorted(by_sp.items()):
    print(f"  {k}: {v}")

# Observed reasons, where the run logged one. Absence of a reason is itself
# informative for #45 — it means the failure mode emitted no event.
if log_path and log_path.exists():
    reasons: dict[str, str] = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        src = str(rec.get("source", "")).removesuffix(".pdf")
        event = rec.get("event")
        if src and event:
            reasons[src] = str(event)
    counted: Counter[str] = Counter()
    for stem in failed:
        counted[reasons.get(stem, "NO EVENT LOGGED")] += 1
    print("\nfailure reasons observed (lead for #45, not a classification):")
    for k, v in counted.most_common():
        print(f"  {k}: {v}")

Path("/tmp/acc57-full/det-failures.txt").write_text("\n".join(failed) + "\n", encoding="utf-8")
print("\nfailure set written to /tmp/acc57-full/det-failures.txt")
