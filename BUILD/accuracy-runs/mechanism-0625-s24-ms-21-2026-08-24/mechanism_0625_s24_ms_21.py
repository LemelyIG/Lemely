"""Direct-observation cause for 0625_s24_ms_21 — the row #45 proved misattributed.

Free, offline, read-only. Prints counts and the mechanism only: no answer
letters and no mark-scheme text are emitted or committed (MISSION §12.7).
"""
from __future__ import annotations
import copy, re
from pathlib import Path

import pdfplumber
from lemely.io.det.mcq import find_mcq_answer_col, parse_mcq_tables

CORPUS = Path("/home/sico/PaperScraper/papers")
STEM = "0625_s24_ms_21"


def main() -> None:
    pdf_path = next(CORPUS.rglob(f"{STEM}.pdf"))
    with pdfplumber.open(pdf_path) as pdf:
        tables = [t for page in pdf.pages[1:] for t in page.extract_tables()]

    base = parse_mcq_tables(tables)
    print(f"{STEM}: tables={len(tables)} parsed_questions={len(base)}")

    # Which table holds the offending cell, and does its answer column resolve?
    for i, t in enumerate(tables):
        data_rows = [r for r in t if r and sum(1 for c in r if (c or "").strip()) >= 2]
        bad = [
            (ri, ci)
            for ri, r in enumerate(data_rows)
            for ci, c in enumerate(r)
            if c and re.search(r"discounted", c, re.I)
        ]
        print(
            f"  table {i}: rows={len(data_rows)} "
            f"answer_col={find_mcq_answer_col(data_rows)} discounted_cells={len(bad)}"
        )

    repaired = copy.deepcopy(tables)
    n = 0
    for t in repaired:
        for r in t:
            for c in range(len(r)):
                if r[c] and re.search(r"discounted", r[c], re.I):
                    r[c] = "D"  # any valid letter; only recovery is under test
                    n += 1
    after = parse_mcq_tables(repaired)
    print(f"\ncells neutralised: {n}")
    print(f"parsed before={len(base)}  after={len(after)}  recovered={len(after) - len(base)}")


if __name__ == "__main__":
    main()
