r"""Budget-BOUNDED sweep for #88 item 2 — ruling C20, hard cap $3.00.

**Why bounded rather than estimated.** The n=1 probe (MISSION 10a's control, the
one that caught the original at $0.42 instead of $13.31) came back AMBIGUOUS:
attempt 1 FAILED costing $0.099146, attempt 2 SUCCEEDED costing $0.076435, total
$0.175581 for one scheme. At the success-only rate 38 schemes is $2.90 with no
margin; at the observed total rate it is $6.67. **One scheme cannot distinguish
"unlucky first call" from "failures are routine"**, and buying more probes to
find out spends the very budget being protected.

So the budget is made the BINDING CONSTRAINT instead of an estimate: schemes are
parsed one at a time in a PRE-COMMITTED order and the run stops the moment the
next scheme could take it past the cap. **It is arithmetically impossible to
exceed $3.00**, and no rate estimate has to be right.

**What this costs, stated rather than hidden:** the sample becomes a
budget-determined PREFIX of the pre-committed ordering rather than a fixed-size
sample. That is still auditable and un-gameable — the ORDER is fixed in advance
by `sha256(salt || stem)` within stratum, exactly as DA1 fixes split assignment
— but the final n is not knowable until the run ends, and any figure computed
over it must report the n it actually reached.

**Stratum-balanced order**: round-robin across strata rather than stratum-by-
stratum, so an early stop degrades coverage EVENLY instead of truncating whole
syllabuses off the end.
"""

from __future__ import annotations

import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))
OUT = ROOT / "BUILD/accuracy-runs/preflight-88-c20-2026-08-27"
STAGE = Path("/home/sico/lemely-fixtures/sweep88-c20")
PAPERS = Path("/home/sico/PaperScraper/papers")

BUDGET_USD = 3.00          # ruling C20 — hard cap, INCLUDING the probe already spent
PROBE_SPENT = 0.175581     # measured, 0580_m21_ms_22 (failed then succeeded)
PROBE_STEM = "0580_m21_ms_22"
# Worst observed single-scheme cost, used as the look-ahead reserve so the cap
# cannot be crossed by the scheme currently in flight.
RESERVE_USD = 0.20


def ledger() -> float:
    return json.loads((ROOT / "outputs/gemini_spend.json").read_text())["cumulative_usd"]


sel = json.loads((OUT / "selection.json").read_text())
stems = [s for s in sel["selected_stems"] if s != PROBE_STEM]


def stratum(stem: str) -> str:
    return f"{stem.split('_')[0]}/p{stem.split('_ms_')[1][0]}"


# Round-robin across strata, preserving the pre-committed within-stratum order.
cells: dict[str, list[str]] = collections.defaultdict(list)
for s in stems:
    cells[stratum(s)].append(s)
order: list[str] = []
while any(cells.values()):
    for k in sorted(cells):
        if cells[k]:
            order.append(cells[k].pop(0))

by = {}
for p in sorted(PAPERS.rglob("*_ms_*.pdf")):
    by.setdefault(p.stem, p)

work = STAGE / "work"
outdir = STAGE / "out"
outdir.mkdir(parents=True, exist_ok=True)

start = ledger()
spent_before_run = PROBE_SPENT
done, failed, stopped_for_budget = [PROBE_STEM], [], False

print(f"budget ${BUDGET_USD:.2f}  |  probe already spent ${PROBE_SPENT:.6f}  |  {len(order)} schemes queued")

for i, stem in enumerate(order, 1):
    spent = spent_before_run + (ledger() - start)
    if spent + RESERVE_USD > BUDGET_USD:
        print(f"\nBUDGET STOP before scheme {i} ({stem}): "
              f"spent ${spent:.4f} + reserve ${RESERVE_USD:.2f} would exceed ${BUDGET_USD:.2f}")
        stopped_for_budget = True
        break
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / f"{stem}.pdf").symlink_to(by[stem])
    r = subprocess.run(
        [str(ROOT / ".venv/bin/lemely"), "parse-mark-schemes", str(work),
         "--output-root", str(outdir), "--use-gemini", "--on-error", "continue"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    ok = (outdir / f"{stem}.json").exists()
    (done if ok else failed).append(stem)
    print(f"[{i:2}/{len(order)}] {stem:22} {'OK ' if ok else 'FAIL'}  "
          f"spent ${spent_before_run + (ledger() - start):.4f}", flush=True)

final_spent = spent_before_run + (ledger() - start)
payload = {
    "label": "sweep88-c20-2026-08-27",
    "issue": 88,
    "ruling": "C20 — budget-bounded, hard cap $3.00",
    "design": "budget-bounded prefix of a pre-committed stratum-balanced order",
    "budget_usd": BUDGET_USD,
    "probe_spent_usd": PROBE_SPENT,
    "total_spent_usd": round(final_spent, 6),
    "selected_n": len(sel["selected_stems"]),
    "parsed_ok": len(done),
    "failed": len(failed),
    "stopped_for_budget": stopped_for_budget,
    "parsed_stems": sorted(done),
    "failed_stems": sorted(failed),
    "coverage_by_stratum": dict(sorted(collections.Counter(stratum(s) for s in done).items())),
}
(OUT / "sweep-result.json").write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nparsed OK {len(done)} | failed {len(failed)} | spent ${final_spent:.4f} of ${BUDGET_USD:.2f}")
print(f"stopped for budget: {stopped_for_budget}")
