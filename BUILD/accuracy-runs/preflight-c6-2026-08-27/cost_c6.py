"""Zero-spend cost of ruling C6 — "deterministic parsing for MCQ ONLY".

C6 restricts the det mark-scheme parser to MCQ papers, routing every non-MCQ
scheme to the paid Gemini path. This prices that, and it MEASURES rather than
scales: the non-MCQ population's own pages are read off the source PDFs, and
the output proxy is re-derived from the committed corpus, exactly as
`preflight-88-2026-08-26/recost_88.py` did.

Token model and rates are UNCHANGED from the #88 preflight so the two numbers
are directly comparable:
    input  = pages * 258 + 1500 prompt overhead per call
    rates  = $0.30/1M input, $2.50/1M output (gemini-2.5-flash, post-M0.2)

Two costs are reported separately, because conflating them is the whole trap:
  (1) ONE-OFF   — rebuilding the committed corpus with 210 schemes moved to Gemini.
  (2) RECURRING — what every future corpus rebuild costs once det no longer
                  serves the non-MCQ population. This is the real commitment.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pymupdf

PAPERS = Path("/home/sico/PaperScraper/papers")
CORPUS = Path("corpus")
TOK_PER_PAGE = 258
PROMPT_OVERHEAD = 1500
USD_IN = 0.30 / 1_000_000
USD_OUT = 2.50 / 1_000_000

manifest = json.loads((CORPUS / "manifest.json").read_text())
parsed_names = list(manifest["file_sha256"])
parsed_stems = {Path(n).stem for n in parsed_names}

by_stem: dict[str, Path] = {}
for p in sorted(PAPERS.rglob("*_ms_*.pdf")):
    by_stem.setdefault(p.stem, p)

# --- partition the committed corpus by paper_type ------------------------
mcq_stems: list[str] = []
nonmcq_stems: list[str] = []
proxy_tokens: list[float] = []
proxy_per_page: list[float] = []

for name in parsed_names:
    doc = json.loads((CORPUS / "mark-schemes" / name).read_text())
    meta = doc.get("metadata", {}) or {}
    stem = Path(name).stem
    is_mcq = str(meta.get("paper_type", "")).lower() == "mcq"
    (mcq_stems if is_mcq else nonmcq_stems).append(stem)
    if is_mcq:
        continue
    ntok = len(json.dumps(doc, separators=(",", ":"))) / 4
    proxy_tokens.append(ntok)
    src = by_stem.get(stem)
    if src is not None:
        try:
            npages = pymupdf.open(str(src)).page_count
            if npages:
                proxy_per_page.append(ntok / npages)
        except Exception:  # noqa: BLE001, S110
            pass

failing = sorted(s for s in by_stem if s not in parsed_stems)

print(f"source mark-scheme PDFs      : {len(by_stem)}")
print(f"committed corpus (det-parsed): {len(parsed_stems)}")
print(f"  of which MCQ (det KEEPS)   : {len(mcq_stems)}")
print(f"  of which non-MCQ (-> paid) : {len(nonmcq_stems)}")
print(f"already-failing (paid today) : {len(failing)}")
print(f"PAID SET UNDER C6            : {len(failing) + len(nonmcq_stems)}"
      f"  ({len(by_stem)} - {len(mcq_stems)} MCQ)")


def pages_of(stems: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in stems:
        src = by_stem.get(s)
        if src is None:
            continue
        try:
            out[s] = pymupdf.open(str(src)).page_count
        except Exception as exc:  # noqa: BLE001
            print(f"  unreadable {s}: {exc}")
    return out


def cost(stems: list[str], label: str) -> dict:
    pg = pages_of(stems)
    tot_pages = sum(pg.values())
    in_tokens = tot_pages * TOK_PER_PAGE + PROMPT_OVERHEAD * len(pg)
    rows = []
    for lbl, out_tokens in (
        ("per-scheme median", statistics.median(proxy_tokens) * len(pg)),
        ("per-scheme mean", statistics.mean(proxy_tokens) * len(pg)),
        ("per-PAGE median", statistics.median(proxy_per_page) * tot_pages),
        ("per-PAGE mean", statistics.mean(proxy_per_page) * tot_pages),
    ):
        rows.append({"label": lbl, "input_tokens": in_tokens,
                     "output_tokens": out_tokens,
                     "total_tokens": in_tokens + out_tokens,
                     "usd": in_tokens * USD_IN + out_tokens * USD_OUT})
    print(f"\n=== {label} — n={len(pg)}, pages {tot_pages} "
          f"(mean {tot_pages/max(len(pg),1):.2f})")
    for r in rows:
        print(f"  {r['label']:<20} {r['total_tokens']/1e6:>7.2f}M  ${r['usd']:>7.2f}")
    return {"n": len(pg), "pages_total": tot_pages,
            "pages_mean": tot_pages / max(len(pg), 1), "scenarios": rows}


incremental = cost(nonmcq_stems, "ONE-OFF: the 210 non-MCQ schemes C6 moves to Gemini")
recurring = cost(sorted(set(failing) | set(nonmcq_stems)),
                 "RECURRING: every future full corpus rebuild under C6")
today = cost(failing, "FOR COMPARISON: the paid set as it stands today (#88 item 2)")

out = {
    "ruling": "C6 — deterministic parsing for MCQ ONLY",
    "parser_sha": manifest["parser_sha"],
    "source_pdfs": len(by_stem),
    "det_parsed_today": len(parsed_stems),
    "mcq_kept_by_det": len(mcq_stems),
    "nonmcq_moved_to_gemini": len(nonmcq_stems),
    "already_failing": len(failing),
    "paid_set_under_c6": len(failing) + len(nonmcq_stems),
    "proxy_n": len(proxy_tokens),
    "one_off_incremental": incremental,
    "recurring_full_rebuild": recurring,
    "today_for_comparison": today,
}
Path("BUILD/accuracy-runs/preflight-c6-2026-08-27/cost_c6.json").write_text(
    json.dumps(out, indent=2) + "\n"
)
print("\nwrote BUILD/accuracy-runs/preflight-c6-2026-08-27/cost_c6.json")
