"""#58 control arm: re-mark the SAME leaves UNPERTURBED, to price the violation.

Inbox item 5 (2026-08-25T17:36:27+03:00) authorises this. The metamorphic run
(``metamorphic-58-2026-08-25``) found ONE violation --
``reorder_mark_points`` on ``0625_s20_qp_31_theory`` q11b, 1 mark -> 2 -- on a
GEMINI-path leaf. Published gemini A/A churn is 0.1565, so a lone violation is
not attributable to the perturbation without a same-input control. This run is
that control.

Design, mirroring the reorder arm exactly so the denominators are comparable:

* For each golden case, compute ``reorder_mark_points``' OWN skip set, so the
  control is restricted to precisely the leaves the reorder arm evaluated live.
* Mark the case twice with the IDENTICAL scheme and IDENTICAL answers.
* Report per-leaf agreement over that same leaf set.

The reorder arm scored 1 violation in 31 live leaves. If this control shows
>= 1 differing leaf over the same 31, the violation sits inside same-input
noise and is NOT evidence of a reorder defect.

Cache is bypassed (E2: ``bypass`` skips the cache read AND the write), so the
two passes are genuinely independent API calls and a cache hit cannot
manufacture agreement -- which would bias this control towards understating
churn, i.e. towards wrongly blaming the perturbation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.accuracy.metamorphic import reorder_mark_points  # noqa: E402
from lemely.io.correction_ai import correct_paper  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
OUT = ROOT / "BUILD" / "accuracy-runs" / "control-58-2026-08-25"


def main() -> None:
    settings = load_settings(cwd=ROOT)
    client = GeminiClient(settings, default_cache_mode="bypass")
    spend_before = client._ledger.total()

    calls = {"n": 0}

    def mark(scheme, answers):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return correct_paper(scheme, answers, gemini_client=client)

    outcomes: list[dict[str, object]] = []
    for case in load_golden_cases(GOLDEN):
        answers = {qid: g.student_answer for qid, g in case.ground_truth.items()}

        # The reorder arm's own skip set, so we score the same leaves it did.
        _, skipped = reorder_mark_points(case.mark_scheme)
        if set(skipped) >= set(case.ground_truth):
            continue  # reorder evaluated nothing here, so neither do we

        pass_a = mark(case.mark_scheme, answers)
        pass_b = mark(case.mark_scheme, answers)
        a = {q.question_id: q.awarded_marks for q in pass_a.questions}
        b = {q.question_id: q.awarded_marks for q in pass_b.questions}
        src = {q.question_id: getattr(q, "marker_source", None) for q in pass_a.questions}

        for qid in case.ground_truth:
            if qid in skipped:
                continue
            before, after = a.get(qid), b.get(qid)
            if before is None or after is None:
                missing = "pass_a" if before is None else "pass_b"
                outcomes.append(
                    {
                        "paper_id": case.paper_id,
                        "question_id": qid,
                        "status": "skipped",
                        "skip_reason": f"leaf was not marked in {missing}",
                    }
                )
                continue
            outcomes.append(
                {
                    "paper_id": case.paper_id,
                    "question_id": qid,
                    "status": "same" if before == after else "differs",
                    "pass_a_marks": before,
                    "pass_b_marks": after,
                    "marker_source": src.get(qid),
                }
            )

    scored = [o for o in outcomes if o["status"] in ("same", "differs")]
    differs = [o for o in scored if o["status"] == "differs"]
    gemini = [o for o in scored if o.get("marker_source") != "deterministic"]
    gemini_differs = [o for o in gemini if o["status"] == "differs"]

    spend_after = client._ledger.total()
    payload = {
        "label": "control-58-2026-08-25",
        "issue": 58,
        "purpose": "same-input control for the single reorder_mark_points violation",
        "authorised_by": "inbox 2026-08-25T17:36:27+03:00 item 5",
        "cache_mode": "bypass",
        "correct_paper_invocations": calls["n"],
        "leaves_scored": len(scored),
        "leaves_differing": len(differs),
        "churn_all_paths": round(len(differs) / len(scored), 4) if scored else None,
        "gemini_leaves_scored": len(gemini),
        "gemini_leaves_differing": len(gemini_differs),
        "churn_gemini_only": round(len(gemini_differs) / len(gemini), 4) if gemini else None,
        "spend_usd_before": round(spend_before, 6),
        "spend_usd_after": round(spend_after, 6),
        "spend_usd_delta": round(spend_after - spend_before, 6),
        "outcomes": outcomes,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"calls={calls['n']} scored={len(scored)} differs={len(differs)}")
    print(f"gemini scored={len(gemini)} differs={len(gemini_differs)}")
    print(f"spend delta = ${spend_after - spend_before:.6f} (ledger {spend_after:.6f})")
    for o in differs:
        print(f"  DIFFERS {o['paper_id']} {o['question_id']} "
              f"{o['pass_a_marks']} -> {o['pass_b_marks']} ({o['marker_source']})")


if __name__ == "__main__":
    main()
