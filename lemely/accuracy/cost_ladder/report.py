"""Render the cost-ladder table: one row per lever, with the gate's reasons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict

HEADER = (
    "lever",
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
    return [
        row.lever,
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


def write_ladder(rows: list[LadderRow], out: Path, *, footer: LadderFooter) -> None:
    lines = [
        "# Cost ladder",
        "",
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
