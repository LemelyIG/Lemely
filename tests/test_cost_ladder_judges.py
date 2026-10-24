"""Sub-project C P1: the accuracy and flip judges, and the real-split checks of the cost judge.

Each check is proven red on a crafted summary that fails only that check.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lemely.accuracy.cost_ladder.gate import (
    RunSummary,
    escalation_notes,
    judge_accuracy_lever,
    judge_cost_lever,
    judge_flip,
    judge_record,
    real_aa_floor,
)

SCRIPTS = ("0625_s23_22", "0625_w24_41")


def _s(**kw: object) -> RunSummary:
    base = RunSummary(
        usd_per_script_mean=0.05,
        latency_p95_ms=1000.0,
        mismarked_parts=frozenset(),
        scored_parts=78,
        id_match_rate=1.0,
        validity_rate=1.0,
        incomplete=(),
        real_scripts=SCRIPTS,
        real_abs_error=20.0,
        real_abs_error_by_run=(20.0, 20.0),
        real_exact_rate=0.8,
        real_within1_rate=0.9,
        real_review_rate=0.30,
        real_binding_passes=2.0,
        real_usd_mean=0.05,
        real_usd_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.05)),
        real_usd_max_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.06)),
        real_escalation_rate=0.05,
        real_escalation_rate_max_script=0.07,
        real_escalation_usd_by_script=(("0625_s23_22", 0.0), ("0625_w24_41", 0.01)),
        real_escalation_triggers=(("confidence", 3),),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_defaults_keep_a_dev_only_summary_unchanged() -> None:
    s = RunSummary(1.0, 1.0, frozenset(), 1, 1.0, 1.0, ())
    assert s.real_scripts == () and s.real_abs_error == 0.0 and s.real_review_rate is None


def test_real_aa_floor_is_the_abs_difference() -> None:
    assert real_aa_floor(_s(real_abs_error=20.0), _s(real_abs_error=17.5)) == 2.5


# --- judge_accuracy_lever -------------------------------------------------------------


def test_accuracy_lever_passes_when_abs_error_falls_by_the_floor() -> None:
    v = judge_accuracy_lever(_s(), _s(real_abs_error=18.0), aa_floor=0, real_aa_floor=2.0)
    assert v.passed, v.reasons


def test_accuracy_lever_fails_when_abs_error_falls_less_than_the_floor() -> None:
    v = judge_accuracy_lever(_s(), _s(real_abs_error=19.0), aa_floor=0, real_aa_floor=2.0)
    assert not v.passed
    assert v.reasons == ("real abs error fell by 1.00 marks, less than the A/A floor 2.00",)


def test_accuracy_lever_fails_on_extra_synthetic_mismarks() -> None:
    v = judge_accuracy_lever(
        _s(),
        _s(real_abs_error=15.0, mismarked_parts=frozenset({"c/1a", "c/2b"})),
        aa_floor=1,
        real_aa_floor=0.0,
    )
    assert v.reasons == ("2 newly mismarked synthetic parts exceed the A/A floor 1",)


def test_accuracy_lever_fails_when_any_script_passes_ten_cents() -> None:
    v = judge_accuracy_lever(
        _s(),
        _s(
            real_abs_error=15.0,
            real_usd_max_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.1001)),
        ),
        aa_floor=0,
        real_aa_floor=0.0,
    )
    assert v.reasons == ("0625_w24_41 $0.1001 exceeds $0.10 per script",)


def test_review_rise_fails_only_when_abs_error_did_not_fall() -> None:
    flat = judge_accuracy_lever(_s(), _s(real_review_rate=0.36), aa_floor=0, real_aa_floor=0.0)
    assert (
        "review rate rose 6.0 points (more than 5) while real abs error did not fall"
        in flat.reasons
    )
    fell = judge_accuracy_lever(
        _s(), _s(real_review_rate=0.36, real_abs_error=19.0), aa_floor=0, real_aa_floor=0.0
    )
    assert fell.passed


def test_accuracy_lever_fails_on_incomplete_and_on_missing_real_split() -> None:
    v = judge_accuracy_lever(
        _s(),
        _s(real_abs_error=15.0, incomplete=("real-1:0625_w24_41 (x)",)),
        aa_floor=0,
        real_aa_floor=0.0,
    )
    assert v.reasons == ("incomplete cases: real-1:0625_w24_41 (x)",)
    v = judge_accuracy_lever(_s(), _s(real_scripts=()), aa_floor=0, real_aa_floor=0.0)
    assert "candidate has no real-split results" in v.reasons


def test_accuracy_lever_rejects_negative_floors() -> None:
    with pytest.raises(ValueError):
        judge_accuracy_lever(_s(), _s(), aa_floor=0, real_aa_floor=-1.0)


# --- judge_cost_lever -----------------------------------------------------------------


def test_cost_lever_dev_only_is_the_existing_judge() -> None:
    dev = RunSummary(1.0, 1000.0, frozenset(), 10, 1.0, 1.0, ())
    v = judge_cost_lever(
        dev,
        replace(dev, usd_per_script_mean=0.9),
        aa_floor=0,
        real_aa_floor=0.0,
        original_latency_p95_ms=1000.0,
    )
    assert v.passed and v.notes == ()


def test_cost_lever_real_only_skips_the_empty_dev_split() -> None:
    empty = {"usd_per_script_mean": 0.0, "scored_parts": 0}
    v = judge_cost_lever(
        _s(**empty),
        _s(**empty, real_usd_mean=0.04),
        aa_floor=0,
        real_aa_floor=0.0,
        original_latency_p95_ms=0.0,
    )
    assert v.passed, v.reasons


def test_cost_lever_fails_when_real_abs_error_rises_past_the_floor() -> None:
    v = judge_cost_lever(
        _s(), _s(real_abs_error=23.0), aa_floor=0, real_aa_floor=2.0, original_latency_p95_ms=1000.0
    )
    assert v.reasons == ("real abs error rose by 3.00 marks, above the A/A floor 2.00",)


def test_cost_lever_fails_when_real_cost_rises() -> None:
    v = judge_cost_lever(
        _s(), _s(real_usd_mean=0.051), aa_floor=0, real_aa_floor=0.0, original_latency_p95_ms=1000.0
    )
    assert v.reasons == ("real cost rose from $0.0500 to $0.0510 per script",)


def test_cost_lever_fails_when_a_script_passes_ten_cents() -> None:
    v = judge_cost_lever(
        _s(),
        _s(real_usd_max_by_script=(("0625_w24_41", 0.11),)),
        aa_floor=0,
        real_aa_floor=0.0,
        original_latency_p95_ms=1000.0,
    )
    assert "0625_w24_41 $0.1100 exceeds $0.10 per script" in v.reasons


def test_cost_lever_reports_real_saving_and_escalation() -> None:
    v = judge_cost_lever(
        _s(), _s(real_usd_mean=0.04), aa_floor=0, real_aa_floor=0.0, original_latency_p95_ms=1000.0
    )
    assert v.passed
    assert v.notes[0] == "real saving 20.0%"
    assert "escalation rate 5.0% (max script 7.0%)" in v.notes


# --- judge_flip -----------------------------------------------------------------------


def test_flip_passes_when_no_worse_than_gemini() -> None:
    gemini = _s(real_abs_error=22.0, real_binding_passes=1.0, real_review_rate=0.21)
    v = judge_flip(gemini, _s(), aa_floor=0)
    assert v.passed, v.reasons


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_s(real_abs_error=22.5), "real abs error 22.50 is above Gemini's 22.00"),
        (
            _s(mismarked_parts=frozenset({"c/1a"})),
            "1 synthetic parts mismarked against Gemini's set exceed the A/A floor 0",
        ),
        (
            _s(real_usd_max_by_script=(("0625_w24_41", 0.12),)),
            "0625_w24_41 $0.1200 exceeds $0.10 per script",
        ),
        (_s(real_binding_passes=0.5), "binding passes 0.5 are below Gemini's 1.0"),
        (
            _s(real_review_rate=0.32),
            "review rate 32.0% is more than 10 points above Gemini's 21.0%",
        ),
        (_s(incomplete=("real-2:0625_s23_22 (x)",)), "incomplete cases: real-2:0625_s23_22 (x)"),
        (_s(real_scripts=("0625_w24_41",)), "real scripts differ from Gemini's"),
    ],
)
def test_flip_fails_on_each_check(candidate: RunSummary, reason: str) -> None:
    gemini = _s(real_abs_error=22.0, real_binding_passes=1.0, real_review_rate=0.21)
    v = judge_flip(gemini, candidate, aa_floor=0)
    assert not v.passed
    assert reason in v.reasons


def test_flip_reports_escalation_next_to_its_checks() -> None:
    v = judge_flip(_s(real_abs_error=22.0), _s(), aa_floor=0)
    assert any(n.startswith("escalation rate") for n in v.notes)
    assert "0625_w24_41 escalation $0.0100 (20.0% of script)" in v.notes


def test_escalation_notes_empty_without_real_split() -> None:
    assert escalation_notes(RunSummary(1.0, 1.0, frozenset(), 1, 1.0, 1.0, ())) == ()


def test_record_judge_passes_unless_incomplete() -> None:
    assert judge_record(_s(), _s()).passed
    assert not judge_record(_s(), _s(incomplete=("x",))).passed


# --- fail-closed fixes ----------------------------------------------------------------


def _cost(base: RunSummary, cand: RunSummary) -> tuple[str, ...]:
    return judge_cost_lever(
        base, cand, aa_floor=0, real_aa_floor=0.0, original_latency_p95_ms=1000.0
    ).reasons


def test_cost_lever_real_only_fails_on_incomplete_even_when_cheaper() -> None:
    empty = {"usd_per_script_mean": 0.0, "scored_parts": 0}
    cand = _s(**empty, real_usd_mean=0.01, incomplete=("real-1:0625_w24_41 (x)",))
    assert "incomplete cases: real-1:0625_w24_41 (x)" in _cost(_s(**empty), cand)


def test_cost_lever_dev_path_reports_incomplete_once() -> None:
    cand = _s(incomplete=("k",))
    assert _cost(_s(), cand).count("incomplete cases: k") == 1


def test_every_judge_fails_on_real_incomplete() -> None:
    cand = _s(real_incomplete=("real-1:0625_w24_41",), real_abs_error=10.0)
    want = "incomplete real cases: real-1:0625_w24_41"
    assert want in _cost(_s(), cand)
    assert want in judge_accuracy_lever(_s(), cand, aa_floor=0, real_aa_floor=0.0).reasons
    assert want in judge_flip(_s(), cand, aa_floor=0).reasons
    assert not judge_record(_s(), cand).passed


def test_cost_lever_fails_when_real_scripts_differ() -> None:
    assert "real scripts differ from the baseline's" in _cost(
        _s(), _s(real_scripts=("0625_w24_41",))
    )


def test_cost_lever_fails_when_one_side_has_no_real_split() -> None:
    assert "baseline has no real-split results" in _cost(_s(real_scripts=()), _s())
    assert "candidate has no real-split results" in _cost(_s(), _s(real_scripts=()))


def test_accuracy_lever_fails_when_abs_error_is_unchanged_even_at_zero_floor() -> None:
    v = judge_accuracy_lever(_s(), _s(real_usd_mean=0.09), aa_floor=0, real_aa_floor=0.0)
    assert not v.passed
    assert v.reasons == (
        "real abs error did not fall (changed by +0.00 marks); a lever must reduce it",
    )


def test_accuracy_lever_fails_when_scored_parts_narrow() -> None:
    v = judge_accuracy_lever(
        _s(), _s(real_abs_error=15.0, scored_parts=70), aa_floor=0, real_aa_floor=0.0
    )
    assert v.reasons == ("scored parts changed from 78 to 70 (narrowed screen)",)


def test_accuracy_lever_fails_when_a_review_rate_is_missing() -> None:
    fell = {"real_abs_error": 15.0}
    v = judge_accuracy_lever(_s(), _s(**fell, real_review_rate=None), aa_floor=0, real_aa_floor=0.0)
    assert v.reasons == ("candidate has no review rate",)
    v = judge_accuracy_lever(_s(real_review_rate=None), _s(**fell), aa_floor=0, real_aa_floor=0.0)
    assert v.reasons == ("baseline has no review rate",)


def test_flip_fails_when_a_review_rate_is_missing() -> None:
    assert judge_flip(_s(), _s(real_review_rate=None), aa_floor=0).reasons == (
        "candidate has no review rate",
    )
    assert judge_flip(_s(real_review_rate=None), _s(), aa_floor=0).reasons == (
        "Gemini rung has no review rate",
    )


def test_flip_fails_when_scored_parts_narrow() -> None:
    v = judge_flip(_s(), _s(scored_parts=70), aa_floor=0)
    assert v.reasons == ("scored parts changed from 78 to 70 (narrowed screen)",)


def test_flip_fails_when_either_side_has_no_real_split() -> None:
    assert (
        "Gemini rung has no real-split results"
        in judge_flip(_s(real_scripts=()), _s(), aa_floor=0).reasons
    )
    assert (
        "candidate has no real-split results"
        in judge_flip(_s(), _s(real_scripts=()), aa_floor=0).reasons
    )


def test_flip_rejects_a_negative_floor() -> None:
    with pytest.raises(ValueError):
        judge_flip(_s(), _s(), aa_floor=-1)
