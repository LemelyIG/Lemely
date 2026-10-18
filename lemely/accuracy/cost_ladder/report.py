"""Render the cost-ladder table: one row per lever, with the gate's reasons."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.gate import Verdict
from lemely.accuracy.cost_ladder.runner import BASELINE_LABEL, LADDER_FILE, read_summary

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from lemely.accuracy.cost_ladder.gate import RunSummary

HEADER = (
    "lever",
    "stacked on",
    "overrides",
    "expected saving",
    "measured saving (2027)",
    "extra mismarks / allowed",
    "id-match",
    "p95 latency",
    "validity",
    "proof",
    "verdict",
    "reasons",
)


@dataclass(frozen=True)
class LadderRow:
    lever: str
    expected_saving: str
    candidate: RunSummary
    verdict: Verdict
    proof: str
    stacked_on: str = BASELINE_LABEL
    overrides: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LadderFooter:
    baseline_usd_2026: float
    baseline_usd_2027: float
    final_usd_2026: float
    final_usd_2027: float
    stop_reason: str


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _row(row: LadderRow) -> list[str]:
    v = row.verdict
    overrides = "; ".join(f"{k}={v}" for k, v in sorted(row.overrides.items())) or "-"
    return [
        row.lever,
        row.stacked_on,
        overrides,
        row.expected_saving,
        f"{v.saving * 100:.1f}%",
        f"{v.extra_mismarks} / {v.allowed_extra}",
        f"{row.candidate.id_match_rate:.3f}",
        f"{row.candidate.latency_p95_ms:.0f} ms",
        f"{row.candidate.validity_rate:.3f}",
        row.proof,
        "ACCEPT" if v.passed else "REJECT",
        "; ".join(v.reasons) or "-",
    ]


def _vs(final: float, base: float) -> str:
    pct = f" ({(1 - final / base) * 100:.1f}% saved)" if base else ""
    return f"${final:.4f} vs ${base:.4f} per script{pct}"


def write_ladder(
    rows: list[LadderRow], out: Path, *, footer: LadderFooter, notes: Sequence[str] = ()
) -> None:
    lines = ["# Cost ladder", ""]
    for note in notes:
        lines += [note, ""]
    lines += [
        "| " + " | ".join(HEADER) + " |",
        "|" + "|".join("---" for _ in HEADER) + "|",
    ]
    lines += ["| " + " | ".join(_cell(c) for c in _row(r)) + " |" for r in rows]
    lines += [
        "",
        "Final against baseline at 2026 rates: "
        + _vs(footer.final_usd_2026, footer.baseline_usd_2026),
        "",
        "Final against baseline at 2027 rates: "
        + _vs(footer.final_usd_2027, footer.baseline_usd_2027),
        "",
        f"Stop reason: {footer.stop_reason}",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def _now_usd(run_dir: Path) -> float:
    data = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return float(data["usd_per_script_mean_now"])


def load_rows(out_dir: Path) -> tuple[list[LadderRow], Path]:
    """Rows in ``ladder.json`` append order, and the run dir of the last accepted row.

    "Final" is the last row that passed, in ladder order; the baseline when none did.
    """
    ladder = out_dir / LADDER_FILE
    labels: list[str] = json.loads(ladder.read_text(encoding="utf-8")) if ladder.is_file() else []
    rows: list[LadderRow] = []
    final = out_dir / BASELINE_LABEL
    for label in labels:
        run_dir = out_dir / label
        v = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
        verdict = Verdict(
            passed=v["passed"],
            tier=v["tier"],
            saving=v["saving"],
            extra_mismarks=v["extra_mismarks"],
            allowed_extra=v["allowed_extra"],
            reasons=tuple(v["reasons"]),
        )
        rows.append(
            LadderRow(
                lever=v["lever"],
                expected_saving=v["expected_saving"],
                candidate=read_summary(run_dir / "summary.json"),
                verdict=verdict,
                proof=v["proof"],
                stacked_on=v.get("against", BASELINE_LABEL),
                overrides=v.get("overrides", {}),
            )
        )
        if verdict.passed:
            final = run_dir
    return rows, final


def write_report(out_dir: Path, *, stop_reason: str) -> Path:
    """Write ``<out_dir>/LADDER.md`` from the screened runs; return its path."""
    rows, final = load_rows(out_dir)
    base = out_dir / BASELINE_LABEL
    base_data = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    notes: list[str] = []
    if "in_run_cache_hits" in base_data:
        notes.append(
            f"Baseline in-run cache hits: {base_data['in_run_cache_hits']} "
            "(calls replayed within rung 0 itself; their cost is not in its total). "
            f"Cache entries written: {base_data.get('cache_entries_written', '?')}; "
            f"cacheable live records: {base_data.get('cacheable_live_records', '?')}."
        )
    footer = LadderFooter(
        baseline_usd_2026=_now_usd(base),
        baseline_usd_2027=read_summary(base / "summary.json").usd_per_script_mean,
        final_usd_2026=_now_usd(final),
        final_usd_2027=read_summary(final / "summary.json").usd_per_script_mean,
        stop_reason=stop_reason,
    )
    target = out_dir / "LADDER.md"
    write_ladder(rows, target, footer=footer, notes=notes)
    return target
