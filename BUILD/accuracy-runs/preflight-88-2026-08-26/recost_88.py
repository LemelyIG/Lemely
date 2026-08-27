"""Zero-spend re-cost of #88 item 2 (Gemini parse of the det-failure set).

Measures, never scales. The det-failure set moved 229 -> 190 when #93 landed,
and the 39 removed are 0625 paper-2 MCQ schemes (short), so a linear 190/229
scale would UNDERESTIMATE the remaining per-paper average. This script
re-measures the failing set's own pages and re-derives the output proxy from
the 289 committed corpus schemes.

Token model is unchanged from the 2026-08-24 preflight so the two are
comparable:  input = pages * 258 + 1500 prompt overhead per call.
Rates: $0.30/1M input, $2.50/1M output (gemini-2.5-flash, post-M0.2).
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
parsed_stems = {Path(n).stem for n in manifest["file_sha256"]}

all_ms = sorted(p for p in PAPERS.rglob("*_ms_*.pdf"))
by_stem: dict[str, Path] = {}
for p in all_ms:
    by_stem.setdefault(p.stem, p)

failing = sorted(s for s in by_stem if s not in parsed_stems)
print(f"source mark-scheme PDFs : {len(by_stem)}")
print(f"parsed (committed corpus): {len(parsed_stems)}")
print(f"FAILING (paid set)       : {len(failing)}")

# --- input side: measured pages of the failing set -----------------------
pages: dict[str, int] = {}
for stem in failing:
    try:
        pages[stem] = pymupdf.open(str(by_stem[stem])).page_count
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable {stem}: {exc}")

tot_pages = sum(pages.values())
print(f"\nfailing-set pages: total {tot_pages}, mean {tot_pages/len(pages):.2f}, "
      f"median {statistics.median(pages.values()):.1f}, max {max(pages.values())}")

# --- output side: proxy from the committed det corpus --------------------
# MCQ schemes are tiny and are NOT in the failing population's shape; size the
# proxy on theory/practical schemes only, and also record a per-page rate so the
# estimate tracks the failing set's own (longer) papers rather than a flat mean.
proxy_tokens: list[float] = []
proxy_per_page: list[float] = []
for name in manifest["file_sha256"]:
    doc = json.loads((CORPUS / "mark-schemes" / name).read_text())
    meta = doc.get("metadata", {}) or {}
    if str(meta.get("paper_type", "")).lower() == "mcq":
        continue
    ntok = len(json.dumps(doc, separators=(",", ":"))) / 4
    proxy_tokens.append(ntok)
    src = by_stem.get(Path(name).stem)
    if src is not None:
        try:
            npages = pymupdf.open(str(src)).page_count
            if npages:
                proxy_per_page.append(ntok / npages)
        except Exception:  # noqa: BLE001, S110
            pass

print(f"\noutput proxy (non-MCQ committed schemes, n={len(proxy_tokens)}): "
      f"median {statistics.median(proxy_tokens):,.0f}  mean {statistics.mean(proxy_tokens):,.0f}")
print(f"per-page proxy (n={len(proxy_per_page)}): "
      f"median {statistics.median(proxy_per_page):,.0f}  mean {statistics.mean(proxy_per_page):,.0f}")

in_tokens = tot_pages * TOK_PER_PAGE + PROMPT_OVERHEAD * len(pages)

rows = []
for label, out_tokens in (
    ("per-scheme median", statistics.median(proxy_tokens) * len(pages)),
    ("per-scheme mean", statistics.mean(proxy_tokens) * len(pages)),
    ("per-PAGE median", statistics.median(proxy_per_page) * tot_pages),
    ("per-PAGE mean", statistics.mean(proxy_per_page) * tot_pages),
):
    usd = in_tokens * USD_IN + out_tokens * USD_OUT
    rows.append((label, in_tokens, out_tokens, in_tokens + out_tokens, usd))

print(f"\n{'scenario':<20} {'input':>10} {'output':>10} {'total':>10} {'USD':>8}")
for label, i, o, t, usd in rows:
    print(f"{label:<20} {i/1e6:>9.2f}M {o/1e6:>9.2f}M {t/1e6:>9.2f}M {usd:>8.2f}")

out = {
    "failing_count": len(failing),
    "failing_stems": failing,
    "pages_total": tot_pages,
    "pages_mean": tot_pages / len(pages),
    "proxy_n": len(proxy_tokens),
    "proxy_median_tokens": statistics.median(proxy_tokens),
    "proxy_mean_tokens": statistics.mean(proxy_tokens),
    "proxy_per_page_median": statistics.median(proxy_per_page),
    "proxy_per_page_mean": statistics.mean(proxy_per_page),
    "scenarios": [
        {"label": r[0], "input_tokens": r[1], "output_tokens": r[2],
         "total_tokens": r[3], "usd": r[4]} for r in rows
    ],
}
Path("BUILD/accuracy-runs/preflight-88-2026-08-26/recost.json").write_text(
    json.dumps(out, indent=2) + "\n"
)
print("\nwrote BUILD/accuracy-runs/preflight-88-2026-08-26/recost.json")
