"""C6 re-costed on MEASURED Gemini rates, replacing a falsified model.

The first C6 preflight (`cost_c6.py`) reused the token model from
`preflight-88-2026-08-26/recost_88.py` and reported that as a strength: it
reproduced #88's four published scenarios to the cent. That reproduction was
real and the inference from it was wrong. **That model had already been
falsified by measurement on the same day** (#88, 2026-08-26): the item-2 sweep
ran, was measured at n=1, confirmed at n=6, and aborted at 6 of 190 because the
estimate was 1.83x under.

Three causes, none of them noise, all of them applying to C6 unchanged — C6
routes the SAME task (Gemini parsing mark schemes from PDF) through the SAME
pipeline:

  1. Input 2.07x under. `pages * 258 + 1500` gives 4,170/call; actual 8,630.
     The PDF goes up through the Files API and is not billed per-page as modelled.
  2. Output 1.35x under, structurally. Predicted 14,790, actual 19,980, of which
     ~36% is thinking tokens. The proxy was det-produced MarkScheme JSON, and a
     det parser does no thinking — so the proxy could not represent that cost AT
     ANY SAMPLE SIZE. More schemes would not have fixed it.
  3. 1.33 Gemini calls per scheme, not 1.00 — retries/fallback modelled as free.

So this script does not model anything. It scales the MEASURED figure:
**$0.07005 per scheme** over #88's population of 190 schemes / 1,967 pages
(10.35 pages/scheme).

Note per #88: `output_tokens` ALREADY INCLUDES `thoughts_tokens`. Pricing
input+output alone reproduces the ledger to the cent; adding thoughts on top
overshoots. Nothing here adds them separately.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path("BUILD/accuracy-runs/preflight-c6-2026-08-27")

# --- measured ground truth, #88 sweep 2026-08-26 -------------------------
M_SCHEMES = 190
M_PAGES = 1967
M_USD_PER_SCHEME = 0.07005
M_TOKENS = 7_250_000

usd_per_page = M_USD_PER_SCHEME * M_SCHEMES / M_PAGES
tok_per_page = M_TOKENS / M_PAGES
tok_per_scheme = M_TOKENS / M_SCHEMES

print(f"MEASURED (#88, n=6 confirmed): ${M_USD_PER_SCHEME}/scheme over "
      f"{M_SCHEMES} schemes / {M_PAGES} pages ({M_PAGES/M_SCHEMES:.2f} pp)")
print(f"  -> ${usd_per_page:.6f}/page, {tok_per_page:,.0f} tokens/page, "
      f"{tok_per_scheme:,.0f} tokens/scheme\n")

# --- C6 populations, measured in cost_c6.json ----------------------------
prior = json.loads((OUT / "cost_c6.json").read_text())
POPS = {
    "one_off_incremental": ("ONE-OFF: the 210 non-MCQ schemes C6 moves", prior["one_off_incremental"]),
    "recurring_full_rebuild": ("RECURRING: every future full corpus rebuild", prior["recurring_full_rebuild"]),
}

LEDGER = 3.146479
CEILING_COMMITTED = 8.00
CEILING_LOCAL = 25.00
TOKEN_CEILING = 5_000_000

rows = {}
for key, (label, pop) in POPS.items():
    n, pages = pop["n"], pop["pages_total"]
    by_page = pages * usd_per_page
    by_scheme = n * M_USD_PER_SCHEME
    tokens = pages * tok_per_page
    old = min(s["usd"] for s in pop["scenarios"]), max(s["usd"] for s in pop["scenarios"])
    rows[key] = {
        "label": label, "n": n, "pages": pages,
        "usd_by_page": round(by_page, 2), "usd_by_scheme": round(by_scheme, 2),
        "tokens": round(tokens),
        "falsified_estimate_usd": [round(old[0], 2), round(old[1], 2)],
        "understatement_factor": round(by_page / old[1], 2),
        "ledger_after_low": round(LEDGER + by_page, 2),
        "ledger_after_high": round(LEDGER + by_scheme, 2),
        "breaches_committed_8": LEDGER + by_page > CEILING_COMMITTED,
        "breaches_local_25": LEDGER + by_page > CEILING_LOCAL,
        "trips_token_ceiling_5M": tokens > TOKEN_CEILING,
    }
    print(f"=== {label} — n={n}, pages={pages}")
    print(f"  WAS (falsified model) : ${old[0]:.2f} – ${old[1]:.2f}")
    print(f"  NOW (measured)        : ${by_page:.2f} (per-page) – ${by_scheme:.2f} (per-scheme)")
    print(f"  understated by        : {by_page/old[1]:.2f}x – {by_scheme/old[0]:.2f}x")
    print(f"  tokens                : {tokens/1e6:.2f}M  (ceiling {TOKEN_CEILING/1e6:.0f}M "
          f"-> {'TRIPS' if tokens > TOKEN_CEILING else 'fits'})")
    print(f"  ledger after          : ${LEDGER + by_page:.2f} – ${LEDGER + by_scheme:.2f}")
    print(f"  vs COMMITTED $8.00    : {'BREACH' if LEDGER + by_page > CEILING_COMMITTED else 'fits'}")
    print(f"  vs local $25.00       : {'BREACH' if LEDGER + by_page > CEILING_LOCAL else 'fits'}\n")

payload = {
    "supersedes": "cost_c6.json — built on the model #88 falsified at 1.83x",
    "basis": "MEASURED $0.07005/scheme, #88 sweep 2026-08-26 (n=1 measured, n=6 confirmed)",
    "measured_usd_per_page": usd_per_page,
    "measured_tokens_per_page": tok_per_page,
    "ledger": LEDGER,
    "ceiling_committed_usd": CEILING_COMMITTED,
    "ceiling_local_gitignored_usd": CEILING_LOCAL,
    "per_run_token_ceiling": TOKEN_CEILING,
    "rows": rows,
}
(OUT / "recost_measured.json").write_text(json.dumps(payload, indent=2) + "\n")
print("wrote recost_measured.json")
