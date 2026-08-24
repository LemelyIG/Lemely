"""Costed preflight for #58 (M1.8) acceptance bullet 4. Spends nothing.

Projects the cost of running the three metamorphic properties against the
golden set under ``cache_mode=bypass``, and reports what evidence that spend
would actually buy.

Two things it does NOT do: call Gemini, and touch the golden fixtures.

Reproduce:
    .venv/bin/python BUILD/accuracy-runs/preflight-58-2026-08-24/preflight_58.py

Writes ``manifest.json`` beside itself.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import cast

from lemely.accuracy.harness import load_golden_cases
from lemely.accuracy.metamorphic import (
    ALL_PROPERTIES,
    PROPERTY_RENAME,
    PROPERTY_REORDER,
    normalise_answer_whitespace,
    rename_mark_point_ids,
    reorder_mark_points,
)
from lemely.core.loose_schemas import QuestionType
from lemely.io.correction_ai import _is_leaf_marked

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GOLDEN = REPO / "tests" / "golden"
#: The A/A floor run is the only corpus-wide record of real per-call cost on
#: the corrected-pricing basis (10 repeats, `bypass`, same golden set).
AA_FLOOR = REPO / "BUILD" / "accuracy-runs" / "aa-floor-2026-08-23-a"


def per_call_rates() -> dict[str, float]:
    """Per-call USD from the ten real A/A repeats, corrected pricing."""
    rates: list[float] = []
    calls = 0
    usd = 0.0
    for path in sorted(glob.glob(str(AA_FLOOR / "manifest-repeat-*.json"))):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        n = int(data["_n_gemini_calls"])
        cost = float(data["_recosted_usd_corrected_pricing"])
        rates.append(cost / n)
        calls += n
        usd += cost
    rates.sort()
    return {
        "source_repeats": len(rates),
        "source_calls": calls,
        "source_usd": round(usd, 6),
        "min": round(rates[0], 6),
        "median": round(rates[len(rates) // 2], 6),
        "max_observed": round(rates[-1], 6),
    }


def project() -> dict[str, object]:
    cases = load_golden_cases(GOLDEN)
    coverage: defaultdict[str, dict[str, object]] = defaultdict(
        lambda: {"leaf_checks": 0, "distinct_leaves": set()}
    )
    per_case: list[dict[str, object]] = []
    total_calls = 0

    for case in cases:
        truth = set(case.ground_truth)
        ai_leaves = [
            q
            for q in case.mark_scheme.all_questions_flat()
            if _is_leaf_marked(q) and q.type != QuestionType.MCQ and q.id in truth
        ]
        if not ai_leaves:
            per_case.append(
                {
                    "paper_id": case.paper_id,
                    "calls": 0,
                    "note": "MCQ-only: deterministic, no Gemini",
                }
            )
            continue

        runs = 1  # the unperturbed baseline
        applied: list[str] = []
        for prop in ALL_PROPERTIES:
            if prop == PROPERTY_REORDER:
                _, skipped = reorder_mark_points(case.mark_scheme)
            elif prop == PROPERTY_RENAME:
                _, skipped = rename_mark_point_ids(case.mark_scheme)
            else:
                answers = {q: g.student_answer for q, g in case.ground_truth.items()}
                normalised = normalise_answer_whitespace(answers)
                skipped = {q: "no-op" for q in answers if normalised[q] == answers[q]}
            live = [q for q in ai_leaves if q.id not in skipped]
            if not live:
                continue
            runs += 1
            applied.append(prop)
            entry = coverage[prop]
            entry["leaf_checks"] = cast("int", entry["leaf_checks"]) + len(live)
            leaves = cast("set[tuple[str, str]]", entry["distinct_leaves"])
            leaves.update((case.paper_id, q.id) for q in live)

        calls = runs * len(ai_leaves)
        total_calls += calls
        per_case.append(
            {
                "paper_id": case.paper_id,
                "fixture_variant": case.fixture_variant,
                "ai_leaves": len(ai_leaves),
                "runs": runs,
                "calls": calls,
                "properties_applied": applied,
            }
        )

    rates = per_call_rates()
    central = total_calls * rates["median"]
    return {
        "per_case": per_case,
        "total_marking_calls": total_calls,
        "per_call_usd": rates,
        "projection_usd": {
            "central": round(central, 4),
            "worst_observed_rate": round(total_calls * rates["max_observed"], 4),
            "proposed_stop_and_ask": round(central * 1.5, 4),
            "basis": (
                "Per-call rate is BLENDED over extract+mark runs; bullet 4 is "
                "marking-only, so the true rate may sit either side. Call count "
                "is exact, which is where the A/A preflight actually went wrong "
                "(it assumed 22 calls/repeat against an actual 74)."
            ),
        },
        "coverage": {
            prop: {
                "leaf_checks": coverage[prop]["leaf_checks"],
                "distinct_leaves": len(
                    cast("set[tuple[str, str]]", coverage[prop]["distinct_leaves"])
                ),
            }
            for prop in ALL_PROPERTIES
        },
    }


def whitespace_gap() -> dict[str, object]:
    """Why bullet 3 has zero coverage, checked rather than asserted."""
    runs = re.compile(r"\s+")
    total = 0
    changed = 0
    for case in load_golden_cases(GOLDEN):
        for golden in case.ground_truth.values():
            total += 1
            if runs.sub(" ", golden.student_answer).strip() != golden.student_answer:
                changed += 1
    return {
        "golden_answers": total,
        "answers_changed_by_normalisation": changed,
        "finding": (
            "Every golden answer is already whitespace-normal, so the transform "
            "is a strict no-op corpus-wide and no spend can buy evidence for "
            "this property. Fixing it means editing the golden fixtures, which "
            "would change the corpus digest and invalidate comparability — an "
            "M0.8 decision for the human, not taken here."
        ),
    }


def main() -> None:
    manifest = {
        "label": "preflight-58-2026-08-24",
        "issue": 58,
        "milestone": "M1.8",
        "kind": "costed preflight (MISSION §10) — projection only, spends nothing",
        "spend_usd": 0.0,
        "gemini_calls": 0,
        "instrument_sha": "fef41ad",
        "command": (".venv/bin/python BUILD/accuracy-runs/preflight-58-2026-08-24/preflight_58.py"),
        "authorisation": (
            "NOT AUTHORISED. No inbox item covers #58. Per the 2026-08-24T15:27 "
            "directive this is a hard stop pending the human; no sweep was run."
        ),
        **project(),
        "whitespace_gap": whitespace_gap(),
        "interpretation": {
            "a_violation": (
                "Existence proof — one leaf whose marks move under a "
                "meaning-preserving perturbation is a real defect at any n."
            ),
            "no_violation": (
                "Weak. At 11 and 21 distinct leaves this licenses only 'no "
                "instability detected at this n', never 'the marker is stable'."
            ),
        },
    }
    out = HERE / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    calls = manifest["total_marking_calls"]
    central = cast("dict[str, object]", manifest["projection_usd"])["central"]
    sys.stdout.write(f"wrote {out}\ncalls={calls} central_usd={central}\n")


if __name__ == "__main__":
    main()
