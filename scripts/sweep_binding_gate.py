#!/usr/bin/env python3
"""Sweep the binding gate's pre-marking thresholds and report what they can catch.

For each setting of the G6 and G7 limits it prints how many golden cases the
checks wrongly hold, how many simulated correct papers they wrongly hold (per
student type), and how many whole-paper shifts they catch. Then, at the chosen
setting, it breaks detection down by how many numeric-answer questions the
scheme has, for whole-paper shifts, partial shifts, splits and drops.

Run with the repository on the path: ``PYTHONPATH=. python scripts/sweep_binding_gate.py``.
"""

from __future__ import annotations

import itertools
import sys
from collections import defaultdict
from dataclasses import astuple, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.core.binding_gate import GateThresholds  # noqa: E402
from tests.binding_students import (  # noqa: E402
    STUDENT_TYPES,
    PaperBits,
    extracted_from,
    load_corpus,
    paper_bits,
    partial_shifts,
    simulated_students,
    split_and_drops,
    valued_leaf_count,
    whole_paper_shifts,
)

MATCHES = (2, 3, 4)
GAPS = (2, 3, 4, 6)
COUNTS = (2, 3, 4)
RATES = (0.20, 0.25, 0.33)
SHIFT_GRID = list(itertools.product(MATCHES, GAPS))
SHAPE_GRID = list(itertools.product(RATES, COUNTS))
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
BANDS = (("fewer than 3", 0, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("more than 10", 11, 10_000))
FALSE_HOLD_OVERALL = 0.02
FALSE_HOLD_ONE_TYPE = 0.05
RANKING_MIN_VALUED = 3
CLOSE_ENOUGH = 0.01


@dataclass(frozen=True)
class Setting:
    matches: int
    gap: int
    count: int
    rate: float

    def thresholds(self) -> GateThresholds:
        return replace(
            GateThresholds(),
            shift_min_matches=self.matches,
            shift_max_gap=self.gap,
            shape_min_count=self.count,
            shape_mismatch_rate=self.rate,
        )


def agreement(a: Setting, b: Setting) -> int:
    """How many of the four limits two settings share (the final tie-break)."""
    return sum(x == y for x, y in zip(astuple(a), astuple(b), strict=True))


def fails(bits: PaperBits, s: Setting) -> bool:
    return bits.ids or bits.shape[(s.rate, s.count)] or bits.shift[(s.matches, s.gap)]


def share(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def golden_bits() -> list[tuple[str, PaperBits]]:
    cases = load_golden_cases(GOLDEN_DIR)
    out = []
    for case in cases:
        answers = {qid: a.student_answer for qid, a in case.ground_truth.items()}
        name = f"{case.paper_id}_{case.fixture_variant}"
        out.append(
            (name, paper_bits(extracted_from(answers), case.mark_scheme, SHAPE_GRID, SHIFT_GRID))
        )
    return out


def main() -> None:
    schemes, skipped = load_corpus()
    print(
        f"corpus schemes with a non-MCQ leaf: {len(schemes)}; "
        f"files that did not validate: {len(skipped)}"
    )
    golden = golden_bits()
    students = [
        (kind, paper_bits(extracted_from(a), sc, SHAPE_GRID, SHIFT_GRID))
        for kind, _n, sc, a in simulated_students(schemes)
    ]
    whole = [
        (by, valued_leaf_count(sc), paper_bits(extracted_from(a), sc, SHAPE_GRID, SHIFT_GRID))
        for by, _n, sc, a in whole_paper_shifts(schemes)
    ]

    rows = []
    for matches, gap, count, rate in itertools.product(MATCHES, GAPS, COUNTS, RATES):
        s = Setting(matches, gap, count, rate)
        held = sum(fails(b, s) for _, b in golden)
        per_type = {
            k: share(
                sum(fails(b, s) for kk, b in students if kk == k),
                sum(kk == k for kk, _ in students),
            )
            for k in STUDENT_TYPES
        }
        overall = share(sum(fails(b, s) for _, b in students), len(students))
        det = {}
        for by in (1, -1):
            pop = [b for d, v, b in whole if d == by and v >= RANKING_MIN_VALUED]
            det[by] = share(sum(fails(b, s) for b in pop), len(pop))
        pop_all = [b for _d, v, b in whole if v >= RANKING_MIN_VALUED]
        det_all = share(sum(fails(b, s) for b in pop_all), len(pop_all))
        own = [b for _d, v, b in whole if v >= matches]
        det_own = share(sum(fails(b, s) for b in own), len(own))
        rows.append((s, held, per_type, overall, det[1], det[-1], det_all, det_own))

    print(f"\nwhole-paper detection ranked on schemes with >= {RANKING_MIN_VALUED} valued leaves")
    print(
        "matches gap count rate | golden_held | false-hold perfect/rand/nearby/all "
        "| detect later/earlier/both | own-pop"
    )
    for s, held, pt, overall, dl, de, da, own in rows:
        print(
            f"{s.matches:>3} {s.gap:>3} {s.count:>3} {s.rate:.2f} | {held:>2}/{len(golden)} | "
            f"{pt['perfect']:.3f}/{pt['weak-random']:.3f}/{pt['weak-nearby']:.3f}/{overall:.3f} | "
            f"{dl:.3f}/{de:.3f}/{da:.3f} | {own:.3f}"
        )

    ok = [
        r
        for r in rows
        if r[1] == 0 and r[3] <= FALSE_HOLD_OVERALL and max(r[2].values()) <= FALSE_HOLD_ONE_TYPE
    ]
    print(f"\nsettings meeting the golden and false-hold limits: {len(ok)} of {len(rows)}")
    if not ok:
        print("NO SETTING MEETS THE LIMITS")
        return
    default = Setting(
        GateThresholds().shift_min_matches,
        GateThresholds().shift_max_gap,
        GateThresholds().shape_min_count,
        GateThresholds().shape_mismatch_rate,
    )
    best = max(ok, key=lambda r: (r[6], -r[3], agreement(r[0], default)))
    default_row = next((r for r in ok if r[0] == default), None)
    print(f"best by the rule: {best[0]} detection {best[6]:.3f} false-hold {best[3]:.3f}")
    if default_row is None:
        print("current defaults do not meet the limits")
        chosen = best
    elif best[6] - default_row[6] <= CLOSE_ENOUGH:
        print(f"current defaults {default} within one point ({default_row[6]:.3f}): keep")
        chosen = default_row
    else:
        chosen = best
    print(f"CHOSEN: {chosen[0]}")
    report(chosen[0], schemes)


def band_of(valued: int) -> str:
    return next(name for name, lo, hi in BANDS if lo <= valued <= hi)


def report(s: Setting, schemes: list[tuple[str, MarkScheme]]) -> None:
    grid_shape, grid_shift = [(s.rate, s.count)], [(s.matches, s.gap)]

    def caught(sc: MarkScheme, answers: dict[str, str]) -> bool:
        return fails(paper_bits(extracted_from(answers), sc, grid_shape, grid_shift), s)

    bands = defaultdict(int)
    for _n, sc in schemes:
        bands[band_of(valued_leaf_count(sc))] += 1
    print("\nschemes per band of valued leaves:", {name: bands[name] for name, _, _ in BANDS})

    def table(title: str, rows: list[tuple[str, MarkScheme, dict[str, str]]]) -> None:
        tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for key, sc, answers in rows:
            t = tally[key + "|" + band_of(valued_leaf_count(sc))]
            t[1] += 1
            t[0] += caught(sc, answers)
        print(f"\n{title}")
        keys = sorted({k.split("|")[0] for k in tally}, key=lambda k: (len(k), k))
        for key in keys:
            parts = []
            hit_all = tot_all = 0
            for name, _, _ in BANDS:
                h, t = tally.get(key + "|" + name, [0, 0])
                hit_all += h
                tot_all += t
                parts.append(f"{name}: {h}/{t} ({share(h, t):.0%})")
            print(
                f"  {key:>10}: "
                + "; ".join(parts)
                + f"; all: {hit_all}/{tot_all} ({share(hit_all, tot_all):.0%})"
            )

    table(
        "whole-paper shift (perfect student), by direction (+1 later, -1 earlier)",
        [(f"{by:+d}", sc, a) for by, _n, sc, a in whole_paper_shifts(schemes)],
    )
    table(
        "partial shift, window of N leaves one later",
        [(str(w), sc, a) for w, _n, sc, a in partial_shifts(schemes)],
    )
    table(
        "split / drop at a seeded leaf in the first half",
        [(k, sc, a) for k, _n, sc, a in split_and_drops(schemes)],
    )
    print("\nfalse holds, simulated correct papers")
    for kind in STUDENT_TYPES:
        rows = [(sc, a) for k, _n, sc, a in simulated_students(schemes) if k == kind]
        h = sum(caught(sc, a) for sc, a in rows)
        print(f"  {kind:>12}: {h}/{len(rows)} ({share(h, len(rows)):.1%})")


if __name__ == "__main__":
    main()
