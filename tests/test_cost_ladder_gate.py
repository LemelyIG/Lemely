"""Tests for the pure cost-ladder gate."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lemely.accuracy.cost_ladder.gate import (
    RunSummary,
    Verdict,
    _over_cap,
    aa_floor,
    escalation_notes,
    judge,
)

ORIG_LAT = 1000.0


def _parts(n: int) -> frozenset[str]:
    return frozenset(f"c/q{i}" for i in range(n))


def _run(**kw: object) -> RunSummary:
    base = RunSummary(
        usd_per_script_mean=1.0,
        latency_p95_ms=1000.0,
        mismarked_parts=frozenset(),
        scored_parts=100,
        id_match_rate=0.9,
        validity_rate=1.0,
        incomplete=(),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_small_tier_passes_within_floor() -> None:
    v = judge(
        _run(),
        _run(mismarked_parts=_parts(2), usd_per_script_mean=0.9),
        aa_floor=2,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert v.passed and v.tier == "small" and v.extra_mismarks == 2 and v.allowed_extra == 2


def test_small_tier_fails_above_floor() -> None:
    v = judge(
        _run(),
        _run(mismarked_parts=_parts(3), usd_per_script_mean=0.9),
        aa_floor=2,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert not v.passed and len(v.reasons) == 1


def test_big_tier_allows_ceil_two_percent() -> None:
    v = judge(
        _run(scored_parts=31),
        _run(scored_parts=31, mismarked_parts=_parts(1), usd_per_script_mean=0.5),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert v.passed and v.tier == "big" and v.allowed_extra == 1


def test_big_tier_fails_two_extra_on_31_parts() -> None:
    v = judge(
        _run(scored_parts=31),
        _run(scored_parts=31, mismarked_parts=_parts(2), usd_per_script_mean=0.5),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert not v.passed and v.tier == "big" and v.allowed_extra == 1


def test_fixed_parts_do_not_offset_new_mismarks() -> None:
    base = _run(mismarked_parts=frozenset({"a/1", "a/2", "a/3"}))
    cand = _run(mismarked_parts=frozenset({"b/1", "b/2"}), usd_per_script_mean=0.9)
    v = judge(base, cand, aa_floor=1, original_latency_p95_ms=ORIG_LAT)
    assert v.extra_mismarks == 2 and not v.passed


def test_id_match_drop_fails() -> None:
    v = judge(_run(), _run(id_match_rate=0.89), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed


def test_validity_drop_fails() -> None:
    v = judge(_run(), _run(validity_rate=0.99), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed


def test_latency_over_double_original_fails() -> None:
    # baseline is a faster stacked config; candidate is still judged vs the original
    base = _run(latency_p95_ms=500.0)
    assert not judge(
        base, _run(latency_p95_ms=2000.1), aa_floor=0, original_latency_p95_ms=ORIG_LAT
    ).passed
    assert judge(
        base, _run(latency_p95_ms=2000.0), aa_floor=0, original_latency_p95_ms=ORIG_LAT
    ).passed


def test_incomplete_run_fails_with_case_named() -> None:
    v = judge(_run(), _run(incomplete=("case-7",)), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed and any("case-7" in r for r in v.reasons)


def test_scored_parts_change_fails() -> None:
    v = judge(_run(), _run(scored_parts=99), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed


def test_aa_floor_is_symmetric_difference() -> None:
    a = _run(mismarked_parts=frozenset({"x", "y"}))
    b = _run(mismarked_parts=frozenset({"y", "z", "w"}))
    assert aa_floor(a, b) == aa_floor(b, a) == 3


def test_all_reasons_reported() -> None:
    v = judge(
        _run(),
        _run(id_match_rate=0.5, validity_rate=0.5),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert len(v.reasons) == 2


def test_zero_baseline_cost_fails() -> None:
    v = judge(
        _run(usd_per_script_mean=0.0),
        _run(usd_per_script_mean=0.0),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert not v.passed and v.saving == 0.0 and v.tier == "small"
    assert any("baseline cost is zero" in r for r in v.reasons)


def test_big_tier_never_stricter_than_small() -> None:
    def verdict(extra: int) -> Verdict:
        return judge(
            _run(scored_parts=31),
            _run(scored_parts=31, mismarked_parts=_parts(extra), usd_per_script_mean=0.65),
            aa_floor=3,
            original_latency_p95_ms=ORIG_LAT,
        )

    ok = verdict(3)
    assert ok.passed and ok.tier == "big" and ok.allowed_extra == 3
    assert not verdict(4).passed


def test_tier_boundary_at_thirty_percent() -> None:
    at = judge(
        _run(usd_per_script_mean=0.1),
        _run(usd_per_script_mean=0.07),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert at.tier == "big"
    above = judge(
        _run(usd_per_script_mean=0.1),
        _run(usd_per_script_mean=0.0700001),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert above.tier == "small"


def test_big_tier_ceil_not_round() -> None:
    v = judge(
        _run(scored_parts=20),
        _run(scored_parts=20, mismarked_parts=_parts(1), usd_per_script_mean=0.5),
        aa_floor=0,
        original_latency_p95_ms=ORIG_LAT,
    )
    assert v.passed and v.tier == "big" and v.allowed_extra == 1


def test_minimal_validity_drop_fails() -> None:
    v = judge(_run(), _run(validity_rate=1.0 - 1e-9), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed


def test_minimal_id_match_drop_fails() -> None:
    v = judge(_run(), _run(id_match_rate=0.9 - 1e-9), aa_floor=0, original_latency_p95_ms=ORIG_LAT)
    assert not v.passed


def test_negative_aa_floor_raises() -> None:
    with pytest.raises(ValueError, match="aa_floor"):
        judge(_run(), _run(), aa_floor=-1, original_latency_p95_ms=ORIG_LAT)


def test_a_script_with_no_cost_figure_is_never_under_the_cap() -> None:
    c = _run(
        real_scripts=("a", "b"),
        real_usd_max_by_script=(("a", 0.05), ("b", None)),
    )
    assert _over_cap(c) == ["b has no cost figure (no result)"]


def test_escalation_notes_survive_a_missing_script() -> None:
    c = _run(
        real_scripts=("a", "b"),
        real_escalation_rate=0.1,
        real_escalation_rate_max_script=0.2,
        real_usd_by_script=(("a", 0.05), ("b", None)),
        real_escalation_usd_by_script=(("a", 0.01), ("b", None)),
    )
    assert "b escalation - (no result)" in escalation_notes(c)
