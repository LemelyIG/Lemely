"""Hard spend caps shared by every cost-ladder run: ledger, pre-run and mid-run checks."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lemely.io.gemini import CallRecord

GEMINI = "gemini"
ANTHROPIC = "anthropic"
SPEND_FILE = "spend.json"
RUN_COST_FILE = "run_cost.json"


class SpendCapError(RuntimeError):
    """A run would start past, or has reached, a provider's combined spend cap."""


@dataclass(frozen=True)
class SpendCaps:
    """Billed-dollar ceilings across ALL cost-ladder runs combined."""

    gemini_usd: float = 3.00
    anthropic_usd: float = 40.00

    def cap_for(self, provider: str) -> float:
        return {GEMINI: self.gemini_usd, ANTHROPIC: self.anthropic_usd}.get(provider, math.inf)


def provider_key(provider: str) -> str:
    """Fold the provider spellings onto the two capped keys."""
    return GEMINI if provider in ("gemini", "google") else provider


def cost_by_provider(records: Sequence[CallRecord]) -> dict[str, float]:
    """Billed USD (`usd_now`) per provider; an unpriced (NaN) call adds nothing it cannot know."""
    totals: dict[str, float] = {}
    for rec in records:
        if not math.isnan(rec.usd_now):
            key = provider_key(rec.provider)
            totals[key] = totals.get(key, 0.0) + rec.usd_now
    return totals


def label_prefix(label: str) -> str:
    """Runs that share a prefix (baseline, baseline_aa) are projected from one another."""
    return re.split(r"[-_]", label, maxsplit=1)[0]


class SpendLedger:
    """`<out_dir>/spend.json`: {provider: usd} accumulated across runs, never reset here."""

    def __init__(self, out_dir: Path) -> None:
        self.path = out_dir / SPEND_FILE
        self._out_dir = out_dir

    def spent(self) -> dict[str, float]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}

    def add(self, costs: Mapping[str, float]) -> dict[str, float]:
        totals = self.spent()
        for provider, usd in costs.items():
            totals[provider] = totals.get(provider, 0.0) + usd
        self._out_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(totals, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return totals

    def projection(self, label: str) -> dict[str, float] | None:
        """Per-provider cost of the latest completed run with the same label prefix."""
        prefix = label_prefix(label)
        costs = [
            p
            for p in self._out_dir.glob(f"*/{RUN_COST_FILE}")
            if p.parent.name != label and label_prefix(p.parent.name) == prefix
        ]
        if not costs:
            return None
        latest = max(costs, key=lambda p: p.stat().st_mtime)
        data = json.loads(latest.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}


def check_can_start(
    spent: Mapping[str, float],
    projected: Mapping[str, float],
    caps: SpendCaps,
) -> None:
    """Abort before any spend when spent + the projected run cost would pass a cap."""
    for provider in sorted(set(spent) | set(projected)):
        total = spent.get(provider, 0.0) + projected.get(provider, 0.0)
        cap = caps.cap_for(provider)
        if total > cap:
            raise SpendCapError(
                f"{provider}: spent ${spent.get(provider, 0.0):.4f} + projected run "
                f"${projected.get(provider, 0.0):.4f} would exceed the ${cap:.2f} cap"
            )


def resolve_projection(
    ledger: SpendLedger, label: str, max_run_usd: Mapping[str, float] | None
) -> dict[str, float]:
    """The run's projected per-provider cost.

    Per provider, the larger of the explicit `--max-run-usd` value and the cost of
    the prefix's last run; an explicit value is never ignored. With neither, refuse.
    """
    last = ledger.projection(label)
    explicit = dict(max_run_usd or {})
    if last is None and not explicit:
        raise SpendCapError(
            f"no completed run shares the prefix of {label!r} to project its cost from; "
            "pass --max-run-usd provider=usd for the first run"
        )
    projected = last or {}
    return {
        provider: max(projected.get(provider, 0.0), explicit.get(provider, 0.0))
        for provider in sorted(set(projected) | set(explicit))
    }


@dataclass
class CapWatch:
    """Per-run running totals; trips once a provider is within one case of its cap.

    Stops when ``spent_before + run_total >= cap - largest_case``: the headroom left
    would not cover another case as dear as the dearest so far. The overshoot is
    bounded by one case's cost, and only when the next case sets a new maximum.
    """

    caps: SpendCaps
    spent_before: Mapping[str, float]
    run_total: dict[str, float] = field(default_factory=dict)
    largest_case: dict[str, float] = field(default_factory=dict)

    def add_case(self, records: Sequence[CallRecord]) -> str | None:
        """Fold one finished case in; return a message when the run must stop."""
        for provider, usd in cost_by_provider(records).items():
            self.run_total[provider] = self.run_total.get(provider, 0.0) + usd
            self.largest_case[provider] = max(self.largest_case.get(provider, 0.0), usd)
        for provider, run_usd in self.run_total.items():
            total = self.spent_before.get(provider, 0.0) + run_usd
            limit = self.caps.cap_for(provider) - self.largest_case[provider]
            if total >= limit:
                return (
                    f"{provider}: ${total:.4f} spent reaches the ${self.caps.cap_for(provider):.2f}"
                    f" cap less one case (${self.largest_case[provider]:.4f})"
                )
        return None
