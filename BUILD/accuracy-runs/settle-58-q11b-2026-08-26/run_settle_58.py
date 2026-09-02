"""#58 / B6: settle the single ``reorder_mark_points`` violation on q11b.

Authorised by inbox B6 (2026-08-26T14:12:38+03:00), ~$0.01: "re-mark q11b
ALONE, perturbed and unperturbed, ~10x each. This supersedes the earlier
control-arm design. Bullet 4 ticks on the result either way."

WHAT THE EARLIER TWO ARMS LEFT UNSETTLED
----------------------------------------
``metamorphic-58-2026-08-25`` scored 1 violation in 31 live leaves:
``0625_s20_qp_31_theory`` q11b, baseline 1 mark -> perturbed 2.
``control-58-2026-08-25`` then re-marked the same leaves unperturbed, twice,
and found 0/62 differing -- which removes "it is just gemini churn" as an
explanation but, at 1/31 against 0/62, is Fisher p=1.000 and cannot call the
violation real either. Both arms were UNDERPOWERED because each spent its
budget on breadth (31 leaves) rather than depth on the one leaf in question.
This run spends it on depth instead.

WHICH CASE, ESTABLISHED RATHER THAN ASSUMED
-------------------------------------------
The report records only ``paper_id`` and all three ``0625_s20_qp_31_theory``
variants share it (DA6 keys a leaf on ``(paper_id, question_id)``; the variant
directory is not in the key). The violated outcome is index 166 of the
outcomes list, which falls in the SECOND ``0625_s20_qp_31_theory`` block --
and ``load_golden_cases`` walks the directories in sorted order, so the second
block is ``_partial``. Its q11b ground truth is 1 mark, matching the report's
``baseline_marks``.

WHY "q11b ALONE" IS THE SAME EXPERIMENT, NOT A CHEAPER ONE
----------------------------------------------------------
``correct_paper`` builds each leaf's prompt from that leaf only, plus
``sibling_prior`` -- and it builds ``sibling_prior`` at all ONLY when
``q.parent_id is not None`` (``correction_ai.py:639-645``). **q11b's
``parent_id`` is ``None``**, so its prompt carries no cross-question context
and is byte-identical whether the scheme holds seven leaves or one. Restricting
the scheme to q11b is therefore a faithful restriction, not a different input.
Had q11b had a parent, this design would have changed the prompt and the
restriction would have been illegitimate.

``reorder_mark_points`` reverses each question's ``answer_points``
independently (``metamorphic.py:189``), so the restricted scheme receives the
identical permutation the full-paper arm applied: p1,p2,p3 -> p3,p2,p1.

CALL COUNT IS EXACT, NOT ESTIMATED
----------------------------------
``mark_question`` issues one call, then a thinking retry only if
``thinking_budget_for['correction_borderline'] > 0`` (the key is absent, so 0)
and a Pro escalation only if ``escalation_model`` is set (it is ``None``).
Both verified from loaded settings. So this run makes exactly 2 x REPEATS
calls and cannot silently multiply.

PRE-COMMITTED ANALYSIS -- fixed before the data exists
------------------------------------------------------
Primary: two-sided Fisher exact on the 2x2 [arm x (awarded_marks >= 2)],
alpha=0.05. Secondary: the full mark distribution of each arm. Three outcomes
were named in advance and all three are reportable:

1. perturbed awards >= 2 significantly more often  -> a REAL reorder defect;
2. both arms vary, no significant difference       -> the violation was
   same-input marking noise on this leaf;
3. both arms constant and equal                    -> the original violation
   does not reproduce at all.

Cache is bypassed (E2: ``bypass`` skips the cache read AND the write), so
every repeat is an independent API call and the shared cache is untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.accuracy.metamorphic import reorder_mark_points  # noqa: E402
from lemely.core.loose_schemas import MarkScheme  # noqa: E402
from lemely.io.correction_ai import correct_paper  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
OUT = ROOT / "BUILD" / "accuracy-runs" / "settle-58-q11b-2026-08-26"

CASE_DIR = "0625_s20_qp_31_theory_partial"
LEAF = "11b"
REPEATS = 10
#: Hard in-process brake. Central projection is $0.0156; this is ~2.5x it, and
#: tripping it aborts rather than continuing to spend (the #37 sweep's brake is
#: the precedent -- it fired, and stopping was the correct outcome).
BRAKE_USD = 0.040


def _restrict(scheme: MarkScheme, leaf_id: str) -> MarkScheme:
    """Return *scheme* holding only the root question *leaf_id*."""
    raw: dict[str, object] = scheme.model_dump(mode="json")
    questions = [q for q in raw["questions"] if q["id"] == leaf_id]  # type: ignore[union-attr,index]
    if len(questions) != 1:
        raise SystemExit(f"expected exactly one root question {leaf_id!r}, got {len(questions)}")
    raw["questions"] = questions
    return MarkScheme.model_validate(raw)


def _fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]], by exact enumeration."""
    from math import comb

    row1, row2 = a + b, c + d
    col1 = a + c
    total = row1 + row2

    def prob(x: int) -> float:
        return comb(row1, x) * comb(row2, col1 - x) / comb(total, col1)

    observed = prob(a)
    lo = max(0, col1 - row2)
    hi = min(row1, col1)
    # Sum every table at most as probable as the observed one (the standard
    # two-sided Fisher convention), with a tolerance so float noise on equally
    # probable tables does not silently drop them.
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= observed * (1 + 1e-9)))


def main() -> None:
    settings = load_settings(cwd=ROOT)
    g = settings.gemini
    if g.escalation_model is not None or g.thinking_budget_for.get("correction_borderline", 0):
        raise SystemExit(
            "escalation is configured, so the call count is no longer exactly 2 x REPEATS; "
            "re-cost the preflight before running"
        )

    client = GeminiClient(settings, default_cache_mode="bypass")
    spend_before = client._ledger.total()

    case = next(
        c for c in load_golden_cases(GOLDEN) if c.scan_path.parent.name == CASE_DIR
    )
    truth = case.ground_truth[LEAF]
    answers = {LEAF: truth.student_answer}

    unperturbed = _restrict(case.mark_scheme, LEAF)
    perturbed, skipped = reorder_mark_points(unperturbed)
    if LEAF in skipped:
        raise SystemExit(f"reorder skipped {LEAF}: {skipped[LEAF]} -- nothing to settle")

    before = [p.id for p in unperturbed.questions[0].answer_points or []]
    after = [p.id for p in perturbed.questions[0].answer_points or []]
    if before == after:
        raise SystemExit("perturbation is a no-op; the arms would be identical")

    repeats: list[dict[str, object]] = []
    aborted: str | None = None
    for rep in range(1, REPEATS + 1):
        # Interleaved, so any drift over the run spreads across both arms
        # instead of loading onto whichever ran last.
        for arm, scheme in (("unperturbed", unperturbed), ("perturbed", perturbed)):
            spent = client._ledger.total() - spend_before
            if spent > BRAKE_USD:
                aborted = f"in-process brake at ${spent:.6f} > ${BRAKE_USD:.3f}"
                break
            result = correct_paper(scheme, answers, gemini_client=client)
            marked = {q.question_id: q for q in result.questions}
            cq = marked.get(LEAF)
            repeats.append(
                {
                    "repeat": rep,
                    "arm": arm,
                    "awarded_marks": None if cq is None else cq.awarded_marks,
                    "confidence": None if cq is None else cq.confidence,
                    "marker_source": None if cq is None else getattr(cq, "marker_source", None),
                    "matched_point_ids": None if cq is None else getattr(cq, "matched_point_ids", None),
                }
            )
        if aborted:
            break

    def marks_of(arm: str) -> list[int]:
        return [
            int(r["awarded_marks"])  # type: ignore[arg-type]
            for r in repeats
            if r["arm"] == arm and r["awarded_marks"] is not None
        ]

    u, p = marks_of("unperturbed"), marks_of("perturbed")
    u_hi, p_hi = sum(1 for m in u if m >= 2), sum(1 for m in p if m >= 2)
    fisher = (
        _fisher_exact_two_sided(p_hi, len(p) - p_hi, u_hi, len(u) - u_hi)
        if u and p
        else None
    )

    spend_after = client._ledger.total()
    payload = {
        "label": "settle-58-q11b-2026-08-26",
        "issue": 58,
        "acceptance_bullet": 4,
        "authorised_by": "inbox B6, 2026-08-26T14:12:38+03:00 (~$0.01)",
        "supersedes": "control-58-2026-08-25 (breadth design, 0/62, Fisher p=1.000)",
        "case_dir": CASE_DIR,
        "leaf": LEAF,
        "leaf_parent_id": unperturbed.questions[0].parent_id,
        "ground_truth_marks": truth.awarded_marks,
        "point_order_unperturbed": before,
        "point_order_perturbed": after,
        "cache_mode": "bypass",
        "repeats_per_arm": REPEATS,
        "aborted": aborted,
        "marks_unperturbed": u,
        "marks_perturbed": p,
        "n_ge2_unperturbed": u_hi,
        "n_ge2_perturbed": p_hi,
        "fisher_exact_two_sided_p": None if fisher is None else round(fisher, 6),
        "alpha": 0.05,
        "spend_usd_before": round(spend_before, 6),
        "spend_usd_after": round(spend_after, 6),
        "spend_usd_delta": round(spend_after - spend_before, 6),
        "repeat_records": repeats,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"case={CASE_DIR} leaf={LEAF} gt={truth.awarded_marks} order {before} -> {after}")
    print(f"unperturbed marks = {u}")
    print(f"perturbed   marks = {p}")
    print(f">=2: perturbed {p_hi}/{len(p)}  unperturbed {u_hi}/{len(u)}  fisher p={fisher}")
    print(f"spend delta = ${spend_after - spend_before:.6f} (ledger {spend_after:.6f})")
    if aborted:
        print(f"ABORTED: {aborted}")


if __name__ == "__main__":
    main()
