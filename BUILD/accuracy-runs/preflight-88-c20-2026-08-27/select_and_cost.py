r"""Right-size #88's item-2 sweep to under $3.00 (ruling C20) — selection + costed preflight.

**The reframing that makes this cheap without narrowing anything that matters.**
Parsing all 190 det-failures yields ~7,115 Gemini-path leaves. DA1's label
budget is ~300 leaves total, of which roughly half sit on the Gemini path — so
the full sweep over-provisions the thing that consumes it by about **47x**. The
binding constraint on this programme is the ~300-leaf HUMAN label budget, not
the scheme count. A stratified subsample is therefore the right-sized design,
not a compromised one.

**Unit is stated explicitly (MISSION 10a / DA25).** The measured rate is
**$0.07005 per SCHEME** (#88, n=1 measured, n=6 confirmed), over a population of
190 schemes / 1,967 pages = 10.35 pages/scheme, i.e. **$0.006768 per PAGE**.
Both are computed below and the HIGHER is reported as the governing estimate.

**Thinking budget is left UNCHANGED at 8000**, deliberately. It is 35.5% of
output and therefore the largest single lever, but these 190 are precisely the
schemes the det parser already FAILED on — the hardest inputs in the corpus, and
the worst place to cut reasoning to save money. Cutting it would also change
`params_fingerprint`, invalidating the cache. Buying MORE schemes we do not need
by risking parse quality on the hard ones is a bad trade.

**Selection is a deterministic hash rank, never a seeded shuffle** — same
discipline DA1 fixes for split assignment: rank = sha256(salt || stem) within
each stratum, so a reviewer recomputes the identical sample from this file alone.
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import pymupdf

CORPUS = Path("corpus")
PAPERS = Path("/home/sico/PaperScraper/papers")
OUT = Path("BUILD/accuracy-runs/preflight-88-c20-2026-08-27")

SALT = "accuracy-88-c20-2026-08-27"     # committed in the open, exactly like DA2's
BUDGET_USD = 3.00                        # ruling C20 — hard cap
TARGET_USD = 2.70                        # aim below it, so the brake is never the plan
USD_PER_SCHEME = 0.07005                 # MEASURED, #88 (n=6 confirmed)
MEAS_SCHEMES, MEAS_PAGES = 190, 1967
USD_PER_PAGE = USD_PER_SCHEME * MEAS_SCHEMES / MEAS_PAGES
FLOOR_PER_STRATUM = 2                    # or all of it, when a stratum is smaller

manifest = json.loads((CORPUS / "manifest.json").read_text())
parsed = {Path(n).stem for n in manifest["file_sha256"]}
by_stem: dict[str, Path] = {}
for p in sorted(PAPERS.rglob("*_ms_*.pdf")):
    by_stem.setdefault(p.stem, p)
failing = sorted(s for s in by_stem if s not in parsed)


def stratum(stem: str) -> str:
    return f"{stem.split('_')[0]}/p{stem.split('_ms_')[1][0]}"


def rank(stem: str) -> str:
    return hashlib.sha256(f"{SALT}|{stem}".encode()).hexdigest()


cells: dict[str, list[str]] = collections.defaultdict(list)
for s in failing:
    cells[stratum(s)].append(s)
for k in cells:
    cells[k].sort(key=rank)          # deterministic, reproducible from this file

# Largest n whose CONSERVATIVE (per-page) estimate stays under TARGET_USD.
pages = {s: pymupdf.open(str(by_stem[s])).page_count for s in failing}


def allocate(n_target: int) -> list[str]:
    """Floor per stratum, then proportional on what remains."""
    picked: dict[str, list[str]] = {}
    for k, v in cells.items():
        picked[k] = v[: min(FLOOR_PER_STRATUM, len(v))]
    used = sum(len(v) for v in picked.values())
    remaining = max(0, n_target - used)
    if remaining:
        pool = sum(len(cells[k]) - len(picked[k]) for k in cells)
        if pool:
            for k in sorted(cells, key=lambda k: -len(cells[k])):
                spare = len(cells[k]) - len(picked[k])
                take = min(spare, round(remaining * (len(cells[k]) - len(picked[k])) / pool))
                picked[k] = cells[k][: len(picked[k]) + take]
            # top up deterministically if rounding left us short
            while sum(len(v) for v in picked.values()) < n_target:
                for k in sorted(cells, key=lambda k: -(len(cells[k]) - len(picked[k]))):
                    if len(picked[k]) < len(cells[k]):
                        picked[k] = cells[k][: len(picked[k]) + 1]
                        break
                else:
                    break
    return sorted(s for v in picked.values() for s in v)


best: list[str] = []
for n in range(len(cells), len(failing) + 1):
    cand = allocate(n)
    pg = sum(pages[s] for s in cand)
    if max(len(cand) * USD_PER_SCHEME, pg * USD_PER_PAGE) > TARGET_USD:
        break
    best = cand

sel_pages = sum(pages[s] for s in best)
by_scheme = len(best) * USD_PER_SCHEME
by_page = sel_pages * USD_PER_PAGE
governing = max(by_scheme, by_page)

print(f"population (det failures) : {len(failing)} schemes, {sum(pages.values())} pages")
print(f"measured rate             : ${USD_PER_SCHEME}/scheme  =  ${USD_PER_PAGE:.6f}/page")
print()
print(f"SELECTED                  : {len(best)} schemes, {sel_pages} pages "
      f"({sel_pages/len(best):.2f} pp vs population {sum(pages.values())/len(failing):.2f})")
print(f"  cost, per-SCHEME unit   : ${by_scheme:.4f}")
print(f"  cost, per-PAGE unit     : ${by_page:.4f}")
print(f"  GOVERNING (the higher)  : ${governing:.4f}   vs budget ${BUDGET_USD:.2f}")
print()
alloc = collections.Counter(stratum(s) for s in best)
for k in sorted(cells):
    print(f"  {k:12} {alloc.get(k,0):3} of {len(cells[k]):3}")

payload = {
    "ruling": "C20 — right-size #88 item 2 to under $3.00",
    "salt": SALT,
    "selection_rule": "sha256(salt||stem) rank within stratum; floor 2/stratum then proportional",
    "strata_axis": "syllabus x paper number (PRE-PARSE observables only, per DA1)",
    "population_schemes": len(failing),
    "selected_schemes": len(best),
    "selected_pages": sel_pages,
    "usd_per_scheme_measured": USD_PER_SCHEME,
    "usd_per_page_derived": USD_PER_PAGE,
    "cost_by_scheme_unit": round(by_scheme, 4),
    "cost_by_page_unit": round(by_page, 4),
    "governing_estimate_usd": round(governing, 4),
    "budget_usd": BUDGET_USD,
    "thinking_budget": "UNCHANGED at 8000 — deliberately not cut; see module docstring",
    "allocation": dict(sorted(alloc.items())),
    "selected_stems": best,
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "selection.json").write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nwrote {OUT}/selection.json")
