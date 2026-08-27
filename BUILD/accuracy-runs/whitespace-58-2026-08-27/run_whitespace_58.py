r"""#58 acceptance bullet 3, live: whitespace normalisation must not change marks.

Bullet 3 was NOT met live. The live bypass run of 2026-08-25 predates #134's
whitespace fixtures, so live it reads **0 held / 71 skipped**; #134's "7 held"
is a zero-spend OFFLINE run. An offline number must not stand in for the live
one this bullet exists to demand, which is why the gap was flagged rather than
banked.

Authorised by ask C4 (2026-08-27). The costed preflight posted to #58 before
any spend found C4's own two figures — "~14 calls" and "~\$0.01" — inconsistent
by ~13x at measured rates, and named which one this run breaks:

  plan A (this run)  1 case,  2 calls, \$0.0200 central   <- chosen
  plan B             12 cases, 13 calls, \$0.1297 central

Rate is MEASURED, not assumed: metamorphic-58-2026-08-25 recorded 28
correct_paper invocations for a \$0.279402 ledger delta = \$0.009979/call.

**Plan B's extra 11 calls buy nothing.** Whether a leaf skips is a pure string
comparison (`perturbed_answers[qid] == text`) decided with no Gemini call at
all, so 11 baseline calls would pay the marker to confirm 64 no-ops that are
already known deterministically at \$0.00. Those 64 leaves ARE reported here,
labelled `determined_offline` so this artifact can never be misread as 71 live
outcomes.

E2: `bypass` skips the cache read AND the write, so the run is side-effect-free
against the shared cache. `refresh` would overwrite it and is never used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.accuracy.metamorphic import (  # noqa: E402
    PROPERTY_WHITESPACE,
    check_cases,
    normalise_answer_whitespace,
)
from lemely.io.correction_ai import correct_paper  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
OUT = ROOT / "BUILD" / "accuracy-runs" / "whitespace-58-2026-08-27"

# In-process brake. The preflight's central estimate is $0.0200; this is ~2.5x
# it, so a runaway stops long before it matters against the COMMITTED $8.00
# ceiling (config.py:111 — not lemely.toml's gitignored local $25.00).
BRAKE_USD = 0.05


def main() -> None:
    settings = load_settings(cwd=ROOT)
    client = GeminiClient(settings, default_cache_mode="bypass")
    spend_before = client._ledger.total()

    all_cases = list(load_golden_cases(GOLDEN))

    # Partition deterministically, at $0.00, BEFORE any call is made.
    live_cases = []
    offline_skips: list[dict[str, str]] = []
    for case in all_cases:
        answers = {qid: g.student_answer for qid, g in case.ground_truth.items()}
        normalised = normalise_answer_whitespace(answers)
        if any(normalised[qid] != text for qid, text in answers.items()):
            live_cases.append(case)
        else:
            offline_skips.extend(
                {
                    "property_name": PROPERTY_WHITESPACE,
                    "paper_id": case.paper_id,
                    "question_id": qid,
                    "status": "skipped",
                    "skip_reason": (
                        "answer has no collapsible whitespace, so the transform is a "
                        "no-op — determined offline by string comparison, never marked"
                    ),
                    "determined_offline": "true",
                }
                for qid in case.ground_truth
            )

    calls = {"n": 0}

    def mark(scheme, answers):  # type: ignore[no-untyped-def]
        spent = client._ledger.total() - spend_before
        if spent > BRAKE_USD:
            raise RuntimeError(f"in-process brake: ${spent:.6f} > ${BRAKE_USD:.2f}")
        calls["n"] += 1
        return correct_paper(scheme, answers, gemini_client=client)

    report = check_cases(live_cases, mark=mark, properties=[PROPERTY_WHITESPACE])

    spend_after = client._ledger.total()
    payload = {
        "label": "whitespace-58-2026-08-27",
        "issue": 58,
        "acceptance_bullet": 3,
        "authorisation": "ask C4, 2026-08-27; plan A of the preflight posted to #58",
        "cache_mode": "bypass",
        "plan": "A — only the case(s) that can exercise the property",
        "cases_total": len(all_cases),
        "cases_marked_live": len(live_cases),
        "cases_skipped_offline": len(all_cases) - len(live_cases),
        "leaves_skipped_offline": len(offline_skips),
        "correct_paper_invocations": calls["n"],
        "brake_usd": BRAKE_USD,
        "spend_usd_before": round(spend_before, 6),
        "spend_usd_after": round(spend_after, 6),
        "spend_usd_delta": round(spend_after - spend_before, 6),
        "report_live": report.to_dict(),
        "outcomes_determined_offline": offline_skips,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    counts = report.counts()
    print(f"cases total={len(all_cases)} marked_live={len(live_cases)} calls={calls['n']}")
    print(f"live counts   = {counts}")
    print(f"offline skips = {len(offline_skips)} leaves")
    print(f"spend delta   = ${spend_after - spend_before:.6f} (ledger {spend_after:.6f})")
    for violation in report.violations:
        print(f"  VIOLATION {violation.property_name} {violation.paper_id} {violation.question_id}")


if __name__ == "__main__":
    main()
