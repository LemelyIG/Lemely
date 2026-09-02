"""#94 acceptance: a per-scheme MCQ loss inventory over the restored corpus.

Det-only. **Zero Gemini calls, zero spend.** Opens each source PDF, reads its
metadata (page 1), and for the MCQ-typed papers runs the answer-key extraction
with :class:`MCQParseDiagnostics` attached, so every discarded table and row is
counted and every rejection carries the value that caused it.

Scope, stated rather than implied: **MCQ-typed papers only.** ``mcq.py`` is the
module #94 instruments, and it runs on no other paper type — including a theory
paper here would pad the denominator with papers the instrumentation cannot say
anything about. Papers whose metadata cannot be read at all are counted
separately and NOT silently dropped; they are the one population this inventory
genuinely cannot see into.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

import pdfplumber  # noqa: E402

from lemely.core.loose_schemas import PaperType  # noqa: E402
from lemely.io.det import metadata as _meta  # noqa: E402
from lemely.io.det.mcq import MCQParseDiagnostics, parse_mcq_tables  # noqa: E402
from lemely.runtime.config import DetParserSettings  # noqa: E402

SOURCES = Path("/home/sico/PaperScraper/papers")
OUT = ROOT / "BUILD" / "accuracy-runs" / "mcq-loss-inventory-2026-08-27"


def main() -> None:
    cfg = DetParserSettings()
    pdfs = sorted(SOURCES.rglob("*_ms_*.pdf"))
    rows: list[dict[str, object]] = []
    metadata_unreadable: list[str] = []
    non_mcq = 0

    for path in pdfs:
        try:
            with pdfplumber.open(path) as pdf:
                meta = _meta.extract_metadata(pdf, path, skip_line_tokens=cfg.skip_line_tokens)
                if meta.paper_type != PaperType.MCQ:
                    non_mcq += 1
                    continue
                tables: list[list[list[str | None]]] = []
                for page in pdf.pages[1:]:
                    tables.extend(page.extract_tables())
        except Exception as exc:  # noqa: BLE001 - inventory must survive one bad file
            metadata_unreadable.append(f"{path.name}: {type(exc).__name__}: {exc}"[:200])
            continue

        diag = MCQParseDiagnostics()
        parse_error: str | None = None
        try:
            parse_mcq_tables(tables, source=path.name, diagnostics=diag)
        except Exception as exc:  # noqa: BLE001 - a ParseError is a result, not a crash
            parse_error = f"{type(exc).__name__}: {exc}"[:200]

        expected = meta.maximum_mark
        rows.append(
            {
                "source": path.name,
                "expected_questions_proxy": expected,
                "parse_error": parse_error,
                **diag.as_log_fields(),
                "shortfall": (
                    expected - diag.questions_parsed
                    if expected and expected > diag.questions_parsed
                    else 0
                ),
                "rejections": diag.rejections,
            }
        )

    lossy = [r for r in rows if r["tables_without_answer_col"]]
    short = [r for r in rows if r["shortfall"]]
    explained = [
        r for r in lossy if r["shortfall"] and r["rows_discarded_data"] >= int(r["shortfall"])
    ]
    offenders: dict[str, int] = {}
    for r in lossy:
        for rej in r["rejections"]:  # type: ignore[union-attr]
            for v in rej.get("disqualifying_values", []):
                offenders[v] = offenders.get(v, 0) + 1

    payload = {
        "label": "mcq-loss-inventory-2026-08-27",
        "issue": 94,
        "scope": "MCQ-typed mark schemes under /home/sico/PaperScraper/papers",
        "gemini_used": False,
        "cost_usd": 0.0,
        "pdfs_seen": len(pdfs),
        "non_mcq_skipped": non_mcq,
        "metadata_unreadable": len(metadata_unreadable),
        "metadata_unreadable_detail": metadata_unreadable[:20],
        "mcq_papers_inventoried": len(rows),
        "papers_with_a_discarded_table": len(lossy),
        "papers_with_a_shortfall": len(short),
        "papers_whose_shortfall_the_discards_could_account_for": len(explained),
        "disqualifying_values_by_frequency": dict(
            sorted(offenders.items(), key=lambda kv: -kv[1])
        ),
        "per_scheme": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inventory.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"pdfs={len(pdfs)} non_mcq={non_mcq} unreadable={len(metadata_unreadable)}")
    print(f"mcq inventoried={len(rows)} with_discarded_table={len(lossy)} with_shortfall={len(short)}")
    print(f"shortfall the discards could account for: {len(explained)}")
    print(f"disqualifying values: {payload['disqualifying_values_by_frequency']}")


if __name__ == "__main__":
    main()
