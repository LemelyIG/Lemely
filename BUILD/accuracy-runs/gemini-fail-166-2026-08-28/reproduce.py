r"""#166 — reproduce ONE 0606 Gemini parse failure with the error visible.

Ruling C22 authorises ~$0.15. The cap is enforced the way C20's was: the live
ledger is read before the call and again after, and the run refuses to start a
second attempt that could cross it. No rate estimate has to be right.

**Why the error was never seen before.** The C20 sweep invoked
`lemely parse-mark-schemes ... --on-error continue` with `capture_output=True`
and printed only whether the output JSON appeared. The failure reason was
captured into a variable and dropped on the floor. This run keeps it.

**Target: `0606_m21_ms_22`** — chosen in PREFLIGHT.md. Still a det failure after
#136 (three of the twelve are not), still 0606, and the one scheme measured
NON-DETERMINISTIC across attempts (failed at $0.099146, then succeeded at
$0.076435). A single reproduction of a flaky failure is worth more than one of a
deterministic one, because it also tells us which of the two it is today.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
OUT = ROOT / "BUILD/accuracy-runs/gemini-fail-166-2026-08-28"
STAGE = Path("/home/sico/lemely-fixtures/gemini-fail-166")
PAPERS = Path("/home/sico/PaperScraper/papers")

BUDGET_USD = 0.15          # ruling C22
STEM = "0606_m21_ms_22"
MAX_ATTEMPTS = 2
RESERVE_USD = 0.11         # the worst measured single attempt on this scheme


def ledger() -> float:
    return json.loads((ROOT / "outputs/gemini_spend.json").read_text())["cumulative_usd"]


src = next(PAPERS.rglob(f"{STEM}.pdf"))
work, outdir = STAGE / "work", STAGE / "out"
for d in (work, outdir):
    d.mkdir(parents=True, exist_ok=True)
link = work / f"{STEM}.pdf"
if not link.exists():
    link.symlink_to(src)

start = ledger()
print(f"target {STEM}  budget ${BUDGET_USD:.2f}  ledger start {start:.6f}", flush=True)

attempts = []
for n in range(1, MAX_ATTEMPTS + 1):
    spent = ledger() - start
    if spent + RESERVE_USD > BUDGET_USD:
        print(f"BUDGET STOP before attempt {n}: spent ${spent:.6f} + reserve "
              f"${RESERVE_USD:.2f} would exceed ${BUDGET_USD:.2f}", flush=True)
        break
    for f in outdir.glob("*.json"):
        f.unlink()
    r = subprocess.run(
        [str(ROOT / ".venv/bin/lemely"), "parse-mark-schemes", str(work),
         "--output-root", str(outdir), "--use-gemini"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=900,
    )
    ok = (outdir / f"{STEM}.json").exists()
    after = ledger()
    attempts.append({
        "attempt": n,
        "ok": ok,
        "returncode": r.returncode,
        "usd": round(after - start - (attempts[-1]["cum_usd"] if attempts else 0.0), 6),
        "cum_usd": round(after - start, 6),
        # kept in full — this is the thing the sweep threw away
        "stdout": r.stdout,
        "stderr": r.stderr,
    })
    print(f"attempt {n}: {'OK' if ok else 'FAIL'} rc={r.returncode} "
          f"cumulative ${after - start:.6f}", flush=True)
    if not ok:
        print("---- stderr ----", flush=True)
        print(r.stderr[-6000:], flush=True)
        print("---- stdout tail ----", flush=True)
        print(r.stdout[-2000:], flush=True)
        break   # a reproduction is what was authorised; stop on the first one

payload = {
    "issue": 166,
    "ruling": "C22 — reproduce one 0606 failure with logging, cap $0.15",
    "target": STEM,
    "budget_usd": BUDGET_USD,
    "ledger_before": start,
    "ledger_after": ledger(),
    "spent_usd": round(ledger() - start, 6),
    "attempts": attempts,
}
(OUT / "reproduce-result.json").write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nspent ${payload['spent_usd']:.6f} of ${BUDGET_USD:.2f}", flush=True)
