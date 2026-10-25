"""Render the cost-ladder table: one row per lever, with the gate's reasons."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.gate import Verdict, escalation_notes
from lemely.accuracy.cost_ladder.runner import (
    AA_FLOOR_FILE,
    BASELINE_LABEL,
    FLIP_VERDICT_FILE,
    LADDER_FILE,
    LadderStateError,
    read_summary,
    require_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
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
    "review rate",
    "proof",
    "verdict",
    "reasons",
)

#: Real-split columns, shown when the ladder has a real split (sub-project C).
REAL_HEADER = (
    "real abs err",
    "exact",
    "within 1",
    "real review",
    "binding pass",
    "max $/script",
    "esc rate",
    "esc $ share",
    "notes",
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
    #: Share of scored parts flagged for teacher review (``summary.json``); None for a
    #: summary written before it was recorded. Reported only: the gate does not read it.
    review_rate: float | None = None


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
        "-" if row.review_rate is None else f"{row.review_rate * 100:.1f}%",
        row.proof,
        "ACCEPT" if v.passed else "REJECT",
        "; ".join(v.reasons) or "-",
    ]


def _pct(rate: float | None) -> str:
    return "-" if rate is None else f"{rate * 100:.1f}%"


def _usd(usd: float | None) -> str:
    return "-" if usd is None else f"${usd:.4f}"


def _escalation_share(c: RunSummary) -> float | None:
    total = sum(usd for _, usd in c.real_usd_by_script if usd is not None)
    esc = sum(usd for _, usd in c.real_escalation_usd_by_script if usd is not None)
    return esc / total if total else None


def _worst_script(c: RunSummary) -> str:
    known = [(k, usd) for k, usd in c.real_usd_max_by_script if usd is not None]
    if not known:
        return "-"
    key, usd = max(known, key=lambda kv: kv[1])
    return f"{key} ${usd:.4f}"


def _abs_error(c: RunSummary) -> str:
    return f"{c.real_abs_error:.1f}{' (incomplete)' if c.real_incomplete else ''}"


def _incomplete_note(c: RunSummary) -> list[str]:
    """A rung with missing real cases must read as incomplete, never as a clean result."""
    return [f"INCOMPLETE real cases: {', '.join(c.real_incomplete)}"] if c.real_incomplete else []


def _real_cells(c: RunSummary, v: Verdict) -> list[str]:
    notes = "; ".join([*_incomplete_note(c), *v.notes]) or "-"
    if not c.real_scripts:
        return ["-"] * (len(REAL_HEADER) - 1) + [notes]
    return [
        _abs_error(c),
        _pct(c.real_exact_rate),
        _pct(c.real_within1_rate),
        _pct(c.real_review_rate),
        f"{c.real_binding_passes:.1f}/{len(c.real_scripts)}",
        _worst_script(c),
        _pct(c.real_escalation_rate),
        _pct(_escalation_share(c)),
        notes,
    ]


def _vs(final: float, base: float) -> str:
    pct = f" ({(1 - final / base) * 100:.1f}% saved)" if base else ""
    return f"${final:.4f} vs ${base:.4f} per script{pct}"


def write_ladder(
    rows: list[LadderRow],
    out: Path,
    *,
    footer: LadderFooter,
    notes: Sequence[str] = (),
    real: bool = False,
) -> None:
    lines = ["# Cost ladder", ""]
    for note in notes:
        lines += [note, ""]
    header = HEADER + REAL_HEADER if real else HEADER
    lines += [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += [
        "| "
        + " | ".join(
            _cell(c) for c in _row(r) + (_real_cells(r.candidate, r.verdict) if real else [])
        )
        + " |"
        for r in rows
    ]
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


def _review_rate(run_dir: Path) -> float | None:
    data = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rate = data.get("review_rate")
    return float(rate) if isinstance(rate, int | float) else None


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
            notes=tuple(v.get("notes", [])),
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
                review_rate=_review_rate(run_dir),
            )
        )
        if verdict.passed:
            final = run_dir
    return rows, final


def write_report(out_dir: Path, *, stop_reason: str) -> Path:
    """Write ``<out_dir>/LADDER.md`` from the screened runs; return its path."""
    base = out_dir / BASELINE_LABEL
    base_summary = require_file(base / "summary.json", "baseline summary (run `baseline` first)")
    rows, final = load_rows(out_dir)
    base_data = json.loads(base_summary.read_text(encoding="utf-8"))
    base_run = read_summary(base_summary)
    real = bool(base_run.real_scripts) or any(r.candidate.real_scripts for r in rows)
    notes: list[str] = []
    if base_run.real_scripts:
        notes.append(
            f"Baseline real split: abs error {base_run.real_abs_error:.1f} marks over "
            f"{len(base_run.real_scripts)} scripts, review {_pct(base_run.real_review_rate)}, "
            f"escalation {_pct(base_run.real_escalation_rate)}, worst script "
            f"{_worst_script(base_run)}."
        )
        notes.extend(_incomplete_note(base_run))
        notes.extend(f"Baseline {n}" for n in escalation_notes(base_run))
    floors_path = out_dir / AA_FLOOR_FILE
    floors = json.loads(floors_path.read_text(encoding="utf-8")) if floors_path.is_file() else {}
    if "real_aa_floor" in floors and "real_marking_aa_floor" in floors:
        notes.append(
            f"Real A/A floors: full pipeline {float(floors['real_aa_floor']):.2f} marks; "
            f"marking only (upstream pinned) {float(floors['real_marking_aa_floor']):.2f} marks."
        )
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
    write_ladder(rows, target, footer=footer, notes=notes, real=real)
    return target


def _runs(*summaries: RunSummary) -> str:
    counts = sorted({len(s.real_abs_error_by_run) for s in summaries if s.real_scripts})
    if not counts:
        return "no live runs recorded"
    return f"{'/'.join(map(str, counts))} live run(s) each"


def write_flip(out_dir: Path, *, candidate: str, gemini: str) -> Path:
    """``<out_dir>/FLIP.md``: the flip judgement, Gemini beside the candidate. Counts only."""
    cand = read_summary(require_file(out_dir / candidate / "summary.json", f"rung {candidate!r}"))
    gem = read_summary(require_file(out_dir / gemini / "summary.json", f"Gemini rung {gemini!r}"))
    verdict = json.loads(
        require_file(out_dir / FLIP_VERDICT_FILE, "flip verdict (run `judge-flip`)").read_text(
            encoding="utf-8"
        )
    )
    if verdict.get("candidate") != candidate or verdict.get("gemini") != gemini:
        raise LadderStateError(
            f"{FLIP_VERDICT_FILE} judged {verdict.get('candidate')!r} against "
            f"{verdict.get('gemini')!r}, not {candidate!r} against {gemini!r}; re-run `judge-flip`"
        )

    def real(c: RunSummary, text: str) -> str:
        return text if c.real_scripts else "-"

    def pair(name: str, fmt: Callable[[RunSummary], str]) -> tuple[str, str, str]:
        return (name, real(gem, fmt(gem)), real(cand, fmt(cand)))

    figures = [
        pair("real abs error (marks)", _abs_error),
        pair("exact leaves", lambda c: _pct(c.real_exact_rate)),
        pair("within 1 mark", lambda c: _pct(c.real_within1_rate)),
        pair("review rate", lambda c: _pct(c.real_review_rate)),
        pair("binding passes", lambda c: f"{c.real_binding_passes:.1f}/{len(c.real_scripts)}"),
        pair("mean $ per script (2027)", lambda c: _usd(c.real_usd_mean)),
        pair("worst script", _worst_script),
        pair("escalation rate", lambda c: _pct(c.real_escalation_rate)),
        pair("escalation $ share", lambda c: _pct(_escalation_share(c))),
        (
            "incomplete real cases",
            str(len(gem.real_incomplete)),
            str(len(cand.real_incomplete)),
        ),
        (
            "synthetic mismarked parts",
            str(len(gem.mismarked_parts)),
            str(len(cand.mismarked_parts)),
        ),
    ]
    lines = [
        "# Flip judgement",
        "",
        f"Candidate `{candidate}` against the Gemini rung `{gemini}`. Real split: the frozen "
        f"reference set, {_runs(gem, cand)}; per-leaf marks stay uncommitted. Counts only.",
        "",
    ]
    detail: list[str] = []
    for who, run in (("Gemini", gem), ("Candidate", cand)):
        detail += [f"{who}: {n}" for n in _incomplete_note(run)]
        detail += [f"{who} {n}" for n in escalation_notes(run)]
    if detail:
        lines += [line for d in detail for line in (d, "")]
    lines += [
        "| figure | Gemini | Claude candidate |",
        "|---|---|---|",
        *(f"| {name} | {g} | {c} |" for name, g, c in figures),
        "",
        "| script | Gemini max $ | Claude max $ | Claude escalation $ |",
        "|---|---|---|---|",
    ]
    gem_max = dict(gem.real_usd_max_by_script)
    cand_max = dict(cand.real_usd_max_by_script)
    cand_esc = dict(cand.real_escalation_usd_by_script)
    for key in dict.fromkeys([*cand_max, *gem_max]):
        lines.append(
            f"| {key} | {_usd(gem_max.get(key))} | {_usd(cand_max.get(key))} | "
            f"{_usd(cand_esc.get(key))} |"
        )
    lines += [
        "",
        f"Verdict: {'PASS' if verdict['passed'] else 'FAIL'}",
        "",
        "Reasons:",
        *(f"- {r}" for r in verdict.get("reasons") or ["none"]),
        "",
        "Notes:",
        *(f"- {n}" for n in verdict.get("notes") or ["none"]),
        "",
    ]
    target = out_dir / "FLIP.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
