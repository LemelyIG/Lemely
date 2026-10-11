#!/usr/bin/env python3
"""Sweep the binding gate's pre-marking thresholds and report what they can catch.

For each setting of the G6 and G7 limits it prints how many golden cases the
checks wrongly hold, how many simulated correct papers they wrongly hold (per
student type), how many whole-paper shifts they catch, and how many papers of a
student who confuses adjacent questions they hold (a sensitivity row, not a limit).
It then applies the threshold rule, prints the decision narrative against the
defaults in ``GateThresholds`` at the time it runs, and, at the chosen setting,
breaks detection down by how many numeric-answer questions the scheme has.

Run with the repository on the path: ``PYTHONPATH=. python scripts/sweep_binding_gate.py``.
"""

from __future__ import annotations

import itertools
import json
import re
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
from lemely.core.binding_gate import (  # noqa: E402
    GateThresholds,
    check_duplicate_ids,
    check_shape,
    check_shift,
    check_unknown_ids,
)
from lemely.core.loose_schemas import MarkScheme as _Scheme  # noqa: E402
from lemely.core.schemas import ExtractedAnswers  # noqa: E402
from tests.binding_students import (  # noqa: E402
    STUDENT_TYPES,
    PaperBits,
    adjacent_students,
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
GAPS = (2, 3, 4, 6, 8, 10, 12)
COUNTS = (2, 3, 4)
RATES = (0.20, 0.25, 0.33, 0.40, 0.50)
ADJACENT_SHARES = (0.10, 0.40)
SHIFT_GRID = list(itertools.product(MATCHES, GAPS))
SHAPE_GRID = list(itertools.product(RATES, COUNTS))
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"
FIXTURE_SCHEME = REPO_ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
BANDS = (("fewer than 3", 0, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("more than 10", 11, 10_000))
FALSE_HOLD_OVERALL = 0.02
FALSE_HOLD_ONE_TYPE = 0.05
RANKING_MIN_VALUED = 3
CLOSE_ENOUGH = 0.01
ADJACENT_COST_LIMIT = 0.02
ORIGINAL_DEFAULTS = (3, 3, 3, 0.25)  # matches, gap, count, rate before the first sweep


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


@dataclass(frozen=True)
class Row:
    setting: Setting
    golden_held: int
    per_type: dict[str, float]
    overall: float
    detect_later: float
    detect_earlier: float
    detect: float
    detect_own: float
    adjacent: dict[float, float]


def agreement(a: Setting, b: Setting) -> int:
    """How many of the four limits two settings share (the final tie-break)."""
    return sum(x == y for x, y in zip(astuple(a), astuple(b), strict=True))


def fails(bits: PaperBits, s: Setting) -> bool:
    return bits.ids or bits.shape[(s.rate, s.count)] or bits.shift[(s.matches, s.gap)]


def share(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def rate_of(bits: list[PaperBits], s: Setting) -> float:
    return share(sum(fails(b, s) for b in bits), len(bits))


def head_defaults() -> Setting:
    d = GateThresholds()
    return Setting(d.shift_min_matches, d.shift_max_gap, d.shape_min_count, d.shape_mismatch_rate)


def bits_of(sc: MarkScheme, answers: dict[str, str]) -> PaperBits:
    return paper_bits(extracted_from(answers), sc, SHAPE_GRID, SHIFT_GRID)


def choose(rows: list[Row], reference: Setting) -> Row:
    return max(rows, key=lambda r: (r.detect, -r.overall, agreement(r.setting, reference)))


def main() -> None:
    schemes, skipped = load_corpus()
    print(
        f"corpus schemes with a non-MCQ leaf: {len(schemes)}; "
        f"files that did not validate: {len(skipped)}"
    )
    golden = []
    for case in load_golden_cases(GOLDEN_DIR):
        answers = {qid: a.student_answer for qid, a in case.ground_truth.items()}
        golden.append(paper_bits(extracted_from(answers), case.mark_scheme, SHAPE_GRID, SHIFT_GRID))
    students = [(kind, bits_of(sc, a)) for kind, _n, sc, a in simulated_students(schemes)]
    adjacent = {
        p: [bits_of(sc, a) for _n, sc, a in adjacent_students(schemes, p)] for p in ADJACENT_SHARES
    }
    whole = [
        (by, valued_leaf_count(sc), bits_of(sc, a)) for by, _n, sc, a in whole_paper_shifts(schemes)
    ]

    rows: list[Row] = []
    for matches, gap, count, rate in itertools.product(MATCHES, GAPS, COUNTS, RATES):
        s = Setting(matches, gap, count, rate)
        per_type = {k: rate_of([b for kk, b in students if kk == k], s) for k in STUDENT_TYPES}
        pop_later = [b for d, v, b in whole if d == 1 and v >= RANKING_MIN_VALUED]
        pop_earlier = [b for d, v, b in whole if d == -1 and v >= RANKING_MIN_VALUED]
        pop_all = [b for _d, v, b in whole if v >= RANKING_MIN_VALUED]
        pop_own = [b for _d, v, b in whole if v >= matches]
        rows.append(
            Row(
                s,
                sum(fails(b, s) for b in golden),
                per_type,
                rate_of([b for _k, b in students], s),
                rate_of(pop_later, s),
                rate_of(pop_earlier, s),
                rate_of(pop_all, s),
                rate_of(pop_own, s),
                {p: rate_of(adjacent[p], s) for p in ADJACENT_SHARES},
            )
        )

    print(f"\nwhole-paper detection ranked on schemes with >= {RANKING_MIN_VALUED} valued leaves")
    print(
        "matches gap count rate | golden_held | false-hold perfect/rand/nearby/all "
        "| detect later/earlier/both | own-pop | adjacent 10%/40% (sensitivity)"
    )
    for r in rows:
        s = r.setting
        print(
            f"{s.matches:>3} {s.gap:>3} {s.count:>3} {s.rate:.2f} | "
            f"{r.golden_held:>2}/{len(golden)} | "
            f"{r.per_type['perfect']:.3f}/{r.per_type['weak-random']:.3f}/"
            f"{r.per_type['weak-nearby']:.3f}/{r.overall:.3f} | "
            f"{r.detect_later:.3f}/{r.detect_earlier:.3f}/{r.detect:.3f} | {r.detect_own:.3f} | "
            f"{r.adjacent[0.10]:.3f}/{r.adjacent[0.40]:.3f}"
        )

    chosen = decide(rows)
    if chosen is not None:
        report(chosen.setting, schemes, students, adjacent)


def decide(rows: list[Row]) -> Row | None:
    """Apply the threshold rule and print the narrative against the current defaults."""
    head = head_defaults()
    ok = [
        r
        for r in rows
        if r.golden_held == 0
        and r.overall <= FALSE_HOLD_OVERALL
        and max(r.per_type.values()) <= FALSE_HOLD_ONE_TYPE
    ]
    print(f"\nsettings meeting the golden and false-hold limits: {len(ok)} of {len(rows)}")
    if not ok:
        print("NO SETTING MEETS THE LIMITS")
        return None
    for label, setting in (
        ("original defaults", Setting(*ORIGINAL_DEFAULTS)),
        ("defaults now in GateThresholds", head),
    ):
        row = next(r for r in rows if r.setting == setting)
        verdict = "meets the limits" if row in ok else "does NOT meet the limits"
        print(
            f"  {label} {setting}: {verdict}; detection {row.detect:.3f}, false-hold "
            f"{row.overall:.3f} (nearby {row.per_type['weak-nearby']:.3f})"
        )
    candidates = ok
    best = choose(candidates, head)
    print(f"best by the rule on the full grid: {best.setting} detection {best.detect:.3f}")
    while best.setting.gap > head.gap:
        at_head_gap = next(r for r in rows if r.setting == replace(best.setting, gap=head.gap))
        cost = best.adjacent[0.10] - at_head_gap.adjacent[0.10]
        print(
            f"  adjacent-confusion (10%) holds at gap {best.setting.gap}: "
            f"{best.adjacent[0.10]:.3f} "
            f"vs {at_head_gap.adjacent[0.10]:.3f} at gap {head.gap} (+{cost:.3f})"
        )
        if cost <= ADJACENT_COST_LIMIT:
            break
        print(f"  more than {ADJACENT_COST_LIMIT:.0%} worse: gap capped at {head.gap}")
        candidates = [r for r in candidates if r.setting.gap <= head.gap]
        best = choose(candidates, head)
        print(f"  best with the cap: {best.setting} detection {best.detect:.3f}")
    head_row = next((r for r in ok if r.setting == head), None)
    if head_row is not None and best.detect - head_row.detect <= CLOSE_ENOUGH:
        print(
            f"defaults now in GateThresholds are eligible and within one point "
            f"({head_row.detect:.3f} vs {best.detect:.3f}): keep"
        )
        chosen = head_row
    else:
        print("defaults now in GateThresholds are not eligible or more than a point behind: change")
        chosen = best
    print(f"CHOSEN: {chosen.setting}")
    return chosen


def band_of(valued: int) -> str:
    return next(name for name, lo, hi in BANDS if lo <= valued <= hi)


def report(
    s: Setting,
    schemes: list[tuple[str, MarkScheme]],
    students: list[tuple[str, PaperBits]],
    adjacent: dict[float, list[PaperBits]],
) -> None:
    only = ([(s.rate, s.count)], [(s.matches, s.gap)])

    def caught(sc: MarkScheme, answers: dict[str, str]) -> bool:
        return fails(paper_bits(extracted_from(answers), sc, *only), s)

    bands: dict[str, int] = defaultdict(int)
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
        for key in sorted({k.split("|")[0] for k in tally}, key=lambda k: (len(k), k)):
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

    everything, _ = load_corpus(include_mcq_only=True)
    shifted = [(sc, a) for _by, _n, sc, a in whole_paper_shifts(everything)]
    seen = sum(caught(sc, a) for sc, a in shifted)
    print(
        f"\nwhole-paper shifts over ALL {len(everything)} validated schemes "
        f"({len(everything) - len(schemes)} multiple-choice only): caught {seen}/{len(shifted)} "
        f"({share(seen, len(shifted)):.1%}); pass unnoticed {len(shifted) - seen}/{len(shifted)} "
        f"({share(len(shifted) - seen, len(shifted)):.1%})"
    )

    print("\nfalse holds, simulated correct papers, by the check that fired")
    for kind in (*STUDENT_TYPES, *(f"adjacent-{p:.0%}" for p in ADJACENT_SHARES)):
        if kind in STUDENT_TYPES:
            bits = [b for k, b in students if k == kind]
        else:
            bits = adjacent[float(kind.split("-")[1].rstrip("%")) / 100]
        by_check = {
            "G1/G2": sum(b.ids for b in bits),
            "G6": sum(b.shape[(s.rate, s.count)] for b in bits),
            "G7": sum(b.shift[(s.matches, s.gap)] for b in bits),
        }
        held = sum(fails(b, s) for b in bits)
        note = "  (sensitivity, not a limit)" if kind not in STUDENT_TYPES else ""
        print(
            f"  {kind:>14}: {held}/{len(bits)} ({share(held, len(bits)):.1%}); "
            + ", ".join(f"{k} {v}" for k, v in by_check.items())
            + note
        )

    print("\nadjacent-confusion holds at every gap (other limits as chosen)")
    for gap in GAPS:
        probe = replace(s, gap=gap)
        print(
            f"  gap {gap:>2}: "
            + ", ".join(f"{p:.0%}: {rate_of(adjacent[p], probe):.1%}" for p in ADJACENT_SHARES)
        )

    fixtures(s)


def fixtures(s: Setting) -> None:
    scheme = _Scheme.model_validate(json.loads(FIXTURE_SCHEME.read_text(encoding="utf-8")))
    limits = s.thresholds()
    print(f"\nrecorded fixtures (0625/41) at {s}")
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        extracted = ExtractedAnswers.model_validate(json.loads(path.read_text(encoding="utf-8")))
        checks = {
            "G1": check_unknown_ids(extracted, scheme),
            "G2": check_duplicate_ids(extracted),
            "G6": check_shape(extracted, scheme, limits),
            "G7": check_shift(extracted, scheme, limits)[0],
        }
        failed = [k for k, c in checks.items() if not c.passed]
        ratio = re.search(r"(\d+) of (\d+)", checks["G6"].detail)
        runs = [int(n) for n in re.findall(r"(\d+) answers hold", checks["G7"].detail)]
        print(
            f"  {path.stem:>16}: fails {', '.join(failed) or 'none'}; "
            f"G6 wrong-kind {ratio[1] + '/' + ratio[2] if ratio else '-'} "
            f"(limit > {limits.shape_mismatch_rate:.0%} and >= {limits.shape_min_count}); "
            f"G7 longest run {max(runs) if runs else 0} (needs {limits.shift_min_matches})"
        )


if __name__ == "__main__":
    main()
