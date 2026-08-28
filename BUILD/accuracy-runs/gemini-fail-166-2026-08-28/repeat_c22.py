r"""#166 / ruling C22 — repeat ONE 0606 scheme to settle intermittent vs systematic.

C22: up to **$0.50 total, then HARD STOP**, spent on ~3 repeats of the SAME
scheme rather than breadth across syllabuses, and report at the cap even if
inconclusive.

**What attempt 1 taught, and why this script exists.** The first reproduction
cost $0.145268 and produced no reason, because
`lemely parse-mark-schemes` renders a summary table and drops
`BatchParseItem.message` — the field the failure reason is already recorded in
(`lemely/io/mark_schemes.py:108-116`). The reason was never missing; it was
never printed. So this calls `process_mark_scheme_batch` **directly**, the same
code path the CLI uses, and keeps the message.

The cap is enforced against the live ledger, counting from BEFORE attempt 1, so
the $0.145268 already spent is inside the $0.50 — not on top of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))
OUT = ROOT / "BUILD/accuracy-runs/gemini-fail-166-2026-08-28"
STAGE = Path("/home/sico/lemely-fixtures/gemini-fail-166")
PAPERS = Path("/home/sico/PaperScraper/papers")

CAP_USD = 0.50                 # ruling C22, HARD
LEDGER_AT_C22_START = 5.588999  # before attempt 1 of reproduce.py
ATTEMPT_1_USD = 0.145268        # measured, already inside the cap
RESERVE_USD = 0.15              # worst measured single attempt on this scheme
TARGET_ATTEMPTS = 3             # C22: "~3 repeats of the SAME scheme"
STEM = "0606_m21_ms_22"


def ledger() -> float:
    return json.loads((ROOT / "outputs/gemini_spend.json").read_text())["cumulative_usd"]


from lemely.io.det import DeterministicMarkSchemeParser  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.io.mark_schemes import process_mark_scheme_batch  # noqa: E402
from lemely.io.parsers import ChainedMarkSchemeParser, GeminiMarkSchemeParser  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402

settings = load_settings()
parser = ChainedMarkSchemeParser(
    primary=DeterministicMarkSchemeParser(cfg=settings.det_parser),
    fallback=GeminiMarkSchemeParser(GeminiClient(settings)),
)

src = next(PAPERS.rglob(f"{STEM}.pdf"))
work, outdir = STAGE / "work", STAGE / "out"
for d in (work, outdir):
    d.mkdir(parents=True, exist_ok=True)
link = work / f"{STEM}.pdf"
if not link.exists():
    link.symlink_to(src)

results: list[dict[str, object]] = [
    {"attempt": 1, "ok": False, "usd": ATTEMPT_1_USD,
     "message": None, "note": "run by reproduce.py; message dropped by the CLI renderer"}
]

print(f"cap ${CAP_USD:.2f} counted from {LEDGER_AT_C22_START:.6f}; "
      f"attempt 1 already spent ${ATTEMPT_1_USD:.6f}", flush=True)

for n in range(2, TARGET_ATTEMPTS + 1):
    spent = ledger() - LEDGER_AT_C22_START
    if spent + RESERVE_USD > CAP_USD:
        print(f"HARD STOP before attempt {n}: spent ${spent:.6f} + reserve "
              f"${RESERVE_USD:.2f} would exceed ${CAP_USD:.2f}", flush=True)
        break
    for f in outdir.glob("*.json"):
        f.unlink()
    before = ledger()
    result = process_mark_scheme_batch(str(work), str(outdir), force=True, parser=parser)
    after = ledger()
    item = result.items[0]
    rec = {
        "attempt": n,
        "status": item.status,
        "ok": item.status == "parsed",
        "usd": round(after - before, 6),
        "message": item.message,      # <- the thing the CLI dropped
    }
    results.append(rec)
    print(f"\nattempt {n}: status={item.status} ${after - before:.6f}", flush=True)
    print(f"  message: {item.message}", flush=True)

spent_total = ledger() - LEDGER_AT_C22_START
payload = {
    "issue": 166,
    "ruling": "C22 — up to $0.50, ~3 repeats of the SAME scheme, report at the cap",
    "target": STEM,
    "cap_usd": CAP_USD,
    "ledger_at_c22_start": LEDGER_AT_C22_START,
    "ledger_now": ledger(),
    "spent_usd": round(spent_total, 6),
    "attempts": results,
    "outcomes": [r.get("status", "failed") for r in results],
}
(OUT / "repeat-result.json").write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nspent ${spent_total:.6f} of ${CAP_USD:.2f} across {len(results)} attempts", flush=True)
