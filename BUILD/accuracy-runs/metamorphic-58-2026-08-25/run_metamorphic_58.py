"""Run #58's metamorphic properties live against the golden set, cache bypassed.

This is acceptance bullet 4: the properties must run against the golden set with
``cache_mode=bypass`` so a cache hit cannot manufacture agreement. Everything
else about #58 was already provable offline; this bullet is the one that costs
money, which is why it needed its own authorisation (inbox A1, re-authorised
2026-08-25T15:00:17+03:00) and its own costed preflight
(``BUILD/accuracy-runs/preflight-58-2026-08-24/``: 168 marking calls,
$0.144 central, $0.216 stop-and-ask).

The run writes the ledger delta it actually observed, not the projection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.accuracy.metamorphic import check_cases  # noqa: E402
from lemely.io.correction_ai import correct_paper  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
OUT = ROOT / "BUILD" / "accuracy-runs" / "metamorphic-58-2026-08-25"


def main() -> None:
    settings = load_settings(cwd=ROOT)
    # E2: `bypass` skips the cache read AND the write, so the run is
    # side-effect-free against the shared cache. `refresh` would overwrite it.
    client = GeminiClient(settings, default_cache_mode="bypass")
    spend_before = client._ledger.total()

    calls = {"n": 0}

    def mark(scheme, answers):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return correct_paper(scheme, answers, gemini_client=client)

    cases = load_golden_cases(GOLDEN)
    report = check_cases(cases, mark=mark)

    spend_after = client._ledger.total()
    payload = {
        "label": "metamorphic-58-2026-08-25",
        "issue": 58,
        "acceptance_bullet": 4,
        "cache_mode": "bypass",
        "cases": len(cases),
        "correct_paper_invocations": calls["n"],
        "spend_usd_before": round(spend_before, 6),
        "spend_usd_after": round(spend_after, 6),
        "spend_usd_delta": round(spend_after - spend_before, 6),
        "report": report.to_dict(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    counts = report.counts()
    print(f"cases={len(cases)} correct_paper_calls={calls['n']}")
    print(f"counts={counts}")
    print(f"spend delta = ${spend_after - spend_before:.6f} (ledger {spend_after:.6f})")
    for violation in report.violations:
        print(f"  VIOLATION {violation.property_name} {violation.paper_id} {violation.question_id}")


if __name__ == "__main__":
    main()
