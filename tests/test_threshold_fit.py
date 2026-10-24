"""Sub-project C P3 lever d: the review- and escalation-threshold fits, at $0."""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.accuracy import threshold_fit as tf
from lemely.accuracy.cost_ladder.real_split import LeafOutcome, RealScriptResult, write_real_results


def _part(conf: float, mismarked: bool, *, refittable: bool = True, flag: bool = False) -> tf.Part:
    return tf.Part("c", f"q{conf}", conf, mismarked, refittable, flag)


def test_recall_pick_is_the_lowest_threshold_that_reaches_the_target() -> None:
    parts = [_part(0.70, True), _part(0.84, True), _part(0.86, False), _part(0.95, False)]
    # Both wrong leaves are flagged from 0.85 up; 0.85 is the lowest such threshold.
    assert tf.recommend_for_recall(parts, recall=0.9) == 0.85


def test_recall_pick_counts_structural_flags() -> None:
    parts = [_part(0.99, True, refittable=False, flag=True), _part(0.60, True)]
    assert tf.recommend_for_recall(parts, recall=1.0) == 0.61


def test_recall_pick_none_when_nothing_is_wrong_or_unreachable() -> None:
    assert tf.recommend_for_recall([_part(0.9, False)]) is None
    assert tf.recommend_for_recall([_part(0.995, True)], recall=1.0) is None


def test_recall_pick_none_over_zero_leaves() -> None:
    assert tf.recommend_for_recall([]) is None


def _leaf(
    qid: str,
    pred: int,
    ref: int,
    conf: float | None,
    *,
    escalated: bool = False,
    source: str = "ai",
    review: bool = False,
    reason: str | None = None,
    pre: float | None | str = "conf",
) -> LeafOutcome:
    pre_conf = conf if pre == "conf" else pre
    assert not isinstance(pre_conf, str)
    return LeafOutcome(
        qid, pred, ref, 2, review, conf, source, reason, escalated,
        "confidence" if escalated else None, pre_conf,
    )  # fmt: skip


def _run(tmp_path: Path, name: str, scripts: list[RealScriptResult]) -> Path:
    path = tmp_path / name / "real_results.json"
    write_real_results(path, scripts)
    return path


def test_parts_from_real_marks_wrong_leaves_and_freezes_the_rest(tmp_path: Path) -> None:
    script = RealScriptResult(
        "a",
        (
            _leaf("1", 1, 2, 0.85),
            _leaf("2", 2, 2, 0.95),
            _leaf("3", 0, 1, 0.70, escalated=True),
            _leaf("4", 0, 0, 0.99, source="deterministic"),
            _leaf("5", 1, 1, 0.97, review=True, reason="uncited_mark"),
        ),
        "pass", 0.05, 0.01, 0.0, 1.0, None,
    )  # fmt: skip
    parts = tf.parts_from_real([_run(tmp_path, "real-1", [script])])
    by = {p.question_id: p for p in parts}
    assert by["1"].mismarked and by["1"].refittable
    assert not by["3"].refittable and not by["4"].refittable and not by["5"].refittable
    assert by["5"].recorded_flag is True
    assert {p.case_key for p in parts} == {"real-1:a"}


def test_unscored_leaves_are_excluded_from_both_fits_and_counted(tmp_path: Path) -> None:
    script = RealScriptResult(
        "a",
        (
            _leaf("1", 1, 2, 0.60),
            _leaf("2", 0, 2, None, source="ai", pre=None),  # dropped: wrong but never scored
        ),
        "pass", 0.05, 0.0, 0.0, 1.0, None,
    )  # fmt: skip
    path = _run(tmp_path, "real-1", [script])
    parts = tf.parts_from_real([path])
    assert [p.question_id for p in parts] == ["1"]
    assert [leaf.confidence for leaf in tf.escalation_leaves([path])] == [0.60]
    assert tf.unscored_leaves([path]) == 1
    # Read as confidence 0 the dropped leaf would be flagged at every threshold; it is not.
    assert tf.recommend_for_recall(parts, recall=1.0) == 0.61


def test_escalation_fit_picks_the_lowest_threshold_reaching_recall_within_the_cap() -> None:
    leaves = [
        tf.EscalationLeaf("r:a", "a", c, w)
        for c, w in [(0.70, True), (0.78, True), (0.82, False), (0.90, False)]
    ]
    fit = tf.fit_escalation_threshold(leaves, case_base_usd={"r:a": 0.05}, usd_per_escalation=0.01)
    assert fit.threshold == 0.79 and fit.escalated == 2 and fit.met_recall
    assert fit.worst_script == "r:a" and fit.worst_script_usd == pytest.approx(0.07)


def test_escalation_fit_backs_off_to_the_cap() -> None:
    leaves = [tf.EscalationLeaf("r:a", "a", c, True) for c in (0.60, 0.70, 0.80)]
    fit = tf.fit_escalation_threshold(leaves, case_base_usd={"r:a": 0.08}, usd_per_escalation=0.01)
    # Two escalations reach $0.10; three would pass it. Recall 2/3 misses the 0.9 target.
    assert fit.escalated == 2 and not fit.met_recall
    assert fit.worst_script_usd == pytest.approx(0.10)


def test_escalation_fit_none_when_even_no_escalation_breaches_the_cap() -> None:
    leaves = [tf.EscalationLeaf("r:a", "a", 0.6, True)]
    fit = tf.fit_escalation_threshold(leaves, case_base_usd={"r:a": 0.11}, usd_per_escalation=0.01)
    assert fit.threshold is None


@pytest.mark.parametrize(
    "leaves",
    [[], [tf.EscalationLeaf("r:a", "a", 0.6, False), tf.EscalationLeaf("r:a", "a", 0.9, False)]],
)
def test_escalation_fit_has_no_basis_without_wrong_leaves(leaves: list[tf.EscalationLeaf]) -> None:
    fit = tf.fit_escalation_threshold(leaves, case_base_usd={"r:a": 0.05}, usd_per_escalation=0.01)
    assert fit == tf.EscalationFit(None, None, 0, None, None, False, tf.REASON_NO_BASIS)


def test_escalation_leaves_skip_non_ai_leaves(tmp_path: Path) -> None:
    script = RealScriptResult(
        "a",
        (_leaf("1", 1, 2, 0.75), _leaf("2", 0, 0, 0.99, source="blank")),
        "pass", 0.05, 0.0, 0.0, 1.0, None,
    )  # fmt: skip
    (leaf,) = tf.escalation_leaves([_run(tmp_path, "real-1", [script])])
    assert leaf.wrong and leaf.confidence == 0.75 and leaf.script == "a"


def test_escalation_cap_binds_on_the_worst_run_not_the_mean() -> None:
    # Run 1 costs 0.075 + 0.012 = 0.087; run 2 costs 0.090 + 0.012 = 0.102 (over the cap).
    # The mean over the runs, 0.0945, would pass.
    leaves = [tf.EscalationLeaf(f"r{n}:a", "a", 0.60, True) for n in (1, 2)]
    fit = tf.fit_escalation_threshold(
        leaves,
        case_base_usd={"r1:a": 0.075, "r2:a": 0.090},
        usd_per_escalation=0.012,
    )
    # Escalating either leaf puts run 2 over $0.10, so nothing escalates (threshold 0.60).
    assert (fit.threshold, fit.escalated, fit.met_recall) == (0.60, 0, False)
    assert fit.reason == tf.REASON_RECALL_UNREACHABLE and fit.worst_script == "r2:a"


def test_escalation_fit_reports_the_worst_case_key() -> None:
    leaves = [tf.EscalationLeaf(f"r{n}:a", "a", 0.60, True) for n in (1, 2)]
    fit = tf.fit_escalation_threshold(
        leaves, case_base_usd={"r1:a": 0.05, "r2:a": 0.08}, usd_per_escalation=0.01
    )
    assert fit.worst_script == "r2:a" and fit.worst_script_usd == pytest.approx(0.09)


def test_escalation_fit_refuses_a_rung_where_a_leaf_escalated() -> None:
    leaves = [
        tf.EscalationLeaf("r:a", "a", 0.6, True),
        tf.EscalationLeaf("r:a", "a", 0.7, False, True),
    ]
    fit = tf.fit_escalation_threshold(leaves, case_base_usd={"r:a": 0.01}, usd_per_escalation=0.01)
    assert fit.threshold is None and fit.reason == tf.REASON_SOURCE_ESCALATED


def test_escalation_leaves_flag_escalated_leaves(tmp_path: Path) -> None:
    script = RealScriptResult(
        "a", (_leaf("1", 2, 2, 0.60, escalated=True),), "pass", 0.05, 0.01, 0.0, 1.0, None
    )
    (leaf,) = tf.escalation_leaves([_run(tmp_path, "real-1", [script])])
    assert leaf.escalated and not leaf.wrong


def test_fit_reasons() -> None:
    base = {"r:a": 0.05}
    none_wrong = [tf.EscalationLeaf("r:a", "a", 0.6, False)]
    assert (
        tf.fit_escalation_threshold(none_wrong, case_base_usd=base, usd_per_escalation=0.01).reason
        == tf.REASON_NO_BASIS
    )
    wrong = [tf.EscalationLeaf("r:a", "a", 0.6, True)]
    assert (
        tf.fit_escalation_threshold(
            wrong, case_base_usd={"r:a": 0.11}, usd_per_escalation=0.01
        ).reason
        == tf.REASON_CAP_BREACHED
    )
    three = [tf.EscalationLeaf("r:a", "a", c, True) for c in (0.6, 0.7, 0.8)]
    assert (
        tf.fit_escalation_threshold(
            three, case_base_usd={"r:a": 0.08}, usd_per_escalation=0.01
        ).reason
        == tf.REASON_RECALL_UNREACHABLE
    )
    ok = tf.fit_escalation_threshold(wrong, case_base_usd=base, usd_per_escalation=0.01)
    assert ok.reason is None and ok.met_recall


def test_escalation_price_uses_only_sonnet_records() -> None:
    recs = [
        {"task_tag": "escalation", "model": tf.ESCALATION_MODEL, "usd_2027": 0.01},
        {"task_tag": "escalation", "model": tf.ESCALATION_MODEL, "usd_2027": 0.03},
        {"task_tag": "escalation", "model": "gemini-x", "usd_2027": 1.0},
        {"task_tag": "correction", "model": tf.ESCALATION_MODEL, "usd_2027": 9.0},
    ]
    price, notes = tf.escalation_price(recs)
    assert price == pytest.approx(0.02)
    assert any("gemini-x" in n and "WARNING" in n for n in notes)


def test_escalation_price_falls_back_to_the_estimate_and_says_so() -> None:
    price, notes = tf.escalation_price(
        [{"task_tag": "escalation", "model": "gemini-x", "usd_2027": 1.0}]
    )
    assert price == tf.ESCALATION_USD_ESTIMATE
    assert any("estimate" in n for n in notes)


def test_duplicate_run_names_are_refused(tmp_path: Path) -> None:
    script = RealScriptResult("a", (_leaf("1", 1, 1, 0.9),), "pass", 0.05, 0.0, 0.0, 1.0, None)
    one = _run(tmp_path / "x", "real-1", [script])
    two = _run(tmp_path / "y", "real-1", [script])
    with pytest.raises(ValueError, match="distinct"):
        tf.parts_from_real([one, two])
    with pytest.raises(ValueError, match="distinct"):
        tf.escalation_leaves([one, two])


def test_escalation_unscored_count_matches_what_is_excluded(tmp_path: Path) -> None:
    script = RealScriptResult(
        "a",
        (
            _leaf("1", 1, 2, 0.60),
            _leaf("2", 0, 2, None, pre=None),
            _leaf("3", 0, 0, None, source="blank", pre=None),
        ),
        "pass", 0.05, 0.0, 0.0, 1.0, None,
    )  # fmt: skip
    path = _run(tmp_path, "real-1", [script])
    assert tf.unscored_leaves([path]) == 2
    assert tf.unscored_escalation_leaves([path]) == 1  # the blank leaf is excluded as non-AI
    assert len(tf.escalation_leaves([path])) == 1


def _cli_run(tmp_path: Path, scripts: list[RealScriptResult], *, records: bool = True) -> Path:
    path = _run(tmp_path, "real-1", scripts)
    if records:
        (path.parent / "records.jsonl").write_text("", encoding="utf-8")
    return path.parent


def test_cli_real_mode_reports_both_fits_and_the_excluded_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import fit_review_threshold as cli

    script = RealScriptResult(
        "a",
        (_leaf("1", 1, 2, 0.60), _leaf("2", 2, 2, 0.95), _leaf("3", 0, 2, None, pre=None)),
        "pass", 0.05, 0.0, 0.0, 1.0, None,
    )  # fmt: skip
    run = _cli_run(tmp_path, [script])
    assert cli.main(["--real", str(run), "--escalation"]) == 0
    out = capsys.readouterr().out
    assert "review fit: leaves excluded for having no confidence (never scored): 1" in out
    assert (
        "escalation fit: AI-marked leaves excluded for having no confidence (never scored): 1"
        in out
    )
    assert "flagging >= 90% of leaves with abs_error > 0: 0.61" in out
    assert "escalation_confidence_threshold: 0.61 (recall 1.000" in out
    assert "using the estimate" in out and "per escalation $0.0056" in out


def test_cli_escalation_fit_prints_the_reason_when_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import fit_review_threshold as cli

    script = RealScriptResult(
        "a", (_leaf("1", 2, 2, 0.60, escalated=True),), "pass", 0.05, 0.01, 0.0, 1.0, None
    )
    assert cli.main(["--real", str(_cli_run(tmp_path, [script])), "--escalation"]) == 0
    assert "reason: source_rung_escalated" in capsys.readouterr().out


def test_cli_rejects_escalation_without_real_and_missing_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import fit_review_threshold as cli

    with pytest.raises(SystemExit):
        cli.main(["results.json", "--escalation"])
    assert "--escalation needs --real" in capsys.readouterr().err
    script = RealScriptResult("a", (_leaf("1", 1, 1, 0.9),), "pass", 0.05, 0.0, 0.0, 1.0, None)
    run = _cli_run(tmp_path, [script], records=False)
    with pytest.raises(SystemExit):
        cli.main(["--real", str(run), "--escalation"])


def test_cli_rejects_duplicate_run_dirs(tmp_path: Path) -> None:
    from scripts import fit_review_threshold as cli

    script = RealScriptResult("a", (_leaf("1", 1, 1, 0.9),), "pass", 0.05, 0.0, 0.0, 1.0, None)
    one = _cli_run(tmp_path / "x", [script])
    two = _cli_run(tmp_path / "y", [script])
    with pytest.raises(SystemExit):
        cli.main(["--real", str(one), "--real", str(two)])
