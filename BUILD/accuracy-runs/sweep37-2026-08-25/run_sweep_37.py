"""#37 (M1.2) gate-9 before/after: the positional fallback, measured.

Authorised by A5 (inbox 2026-08-25T14:24:52). The costed preflight is posted on
#37: $0.0625 per extract+mark pass measured from ablation-2026-08-24-a's own arm
over these same 11 golden cases, $0.125 central for two arms, $0.25
stop-and-ask. Ceiling $20.00.

DESIGN — extraction runs ONCE, and both arms share it.

The naive sweep extracts twice. That would be wrong here, and the #58 control
arm is why: a single-repeat A/B over a Gemini path cannot separate the change
from ordinary nondeterminism. Extraction is the nondeterministic step; the
change under test is purely downstream of it. So this script extracts once per
case, keeps the RAW pre-normalisation answers, and feeds the identical raw
extraction through both normalisers.

That buys three things:
  * the arms are genuinely PAIRED, so McNemar applies rather than an unpaired
    comparison of two noisy samples;
  * extraction churn is eliminated by construction instead of hoped to average
    out at n=11;
  * extraction spend is halved.

Marking still runs twice, because different ids produce different marking.

HOW THE RAW EXTRACTION IS OBTAINED: `GeminiAnswerExtractor.__call__` normalises
before returning, so there is no public raw path. Rather than duplicate the
extractor (which would silently drift from production), this patches
`normalize_extracted_answers` to an identity pass-through for the duration of
the extraction call only. Production code is not modified.

A5 CONDITION 3, and the problem with it, stated rather than worked around: the
condition asks for `id_positional_fallback` warning lines counted in the SAME
run. This branch DELETES that warning, so the new arm emits zero by
construction and counting there would report a meaningless 0. The count is
therefore taken from the OLD arm, whose normaliser is reproduced below verbatim
as it stood before the deletion. That is still one run, not two.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
sys.path.insert(0, str(ROOT))

from lemely.accuracy.harness import load_golden_cases  # noqa: E402
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers  # noqa: E402
from lemely.io import answer_extraction as ae  # noqa: E402
from lemely.io.correction_ai import correct_paper  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import load_settings  # noqa: E402
from lemely.web.services.grading import extract_answers  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
OUT = ROOT / "BUILD" / "accuracy-runs" / "sweep37-pending"

#: Preflight stop-and-ask. The run aborts rather than silently overrunning —
#: the #58 metamorphic run overran its estimate 1.94x with nothing watching.
STOP_AND_ASK_USD = 0.25


def old_normalize(
    extracted: ExtractedAnswers, manifest_ids: list[str]
) -> tuple[ExtractedAnswers, int]:
    """`normalize_extracted_answers` EXACTLY as it stood before #37 deleted the
    fallback, plus a counter for how many times the fallback fired.

    Reproduced here rather than imported because the point of the run is to
    compare against code that no longer exists.
    """
    canonical_map = {ae._canonical_id(mid): mid for mid in manifest_ids}
    claimed: set[str] = set()
    new_answers: list[ExtractedAnswer] = []
    unmatched_positions: list[int] = []

    for ans in extracted.answers:
        canon = ae._canonical_id(ans.question_id)
        if canon in canonical_map:
            target = canonical_map[canon]
            new_answers.append(ans.model_copy(update={"question_id": target}))
            claimed.add(target)
        else:
            unmatched_positions.append(len(new_answers))
            new_answers.append(ans)

    unclaimed = [mid for mid in manifest_ids if mid not in claimed]
    fallback_fires = 0
    for seq, pos in enumerate(unmatched_positions):
        if seq < len(unclaimed):
            fallback_fires += 1
            new_answers[pos] = new_answers[pos].model_copy(
                update={"question_id": unclaimed[seq]}
            )

    return extracted.model_copy(update={"answers": new_answers}), fallback_fires


def main() -> None:
    settings = load_settings(cwd=ROOT)
    # E2: bypass skips the cache read AND the write, so this is side-effect-free
    # against the shared cache and a cache hit cannot manufacture agreement.
    client = GeminiClient(settings, default_cache_mode="bypass")
    spend_before = client._ledger.total()

    per_case: list[dict[str, object]] = []
    total_fallback_fires = 0

    for case in load_golden_cases(GOLDEN):
        if case.scan_path is None:
            continue

        manifest_ids = [
            q.id for q in case.mark_scheme.all_questions_flat() if q.marks > 0 and not q.parts
        ]

        # --- extract ONCE, capturing the raw pre-normalisation answers -------
        captured: dict[str, ExtractedAnswers] = {}

        def _capture(extracted: ExtractedAnswers, _ids: list[str]) -> ExtractedAnswers:
            captured["raw"] = extracted
            return extracted

        original = ae.normalize_extracted_answers
        ae.normalize_extracted_answers = _capture  # type: ignore[assignment]
        try:
            extract_answers(case.scan_path, case.mark_scheme, gemini_client=client)
        finally:
            ae.normalize_extracted_answers = original  # type: ignore[assignment]
        raw = captured["raw"]

        # --- two normalisers over the SAME raw extraction --------------------
        old_answers, fires = old_normalize(raw, manifest_ids)
        new_answers = original(raw, manifest_ids)
        total_fallback_fires += fires

        gt_ids = set(case.ground_truth)
        old_ids = {a.question_id for a in old_answers.answers}
        new_ids = {a.question_id for a in new_answers.answers}

        old_marks = {
            q.question_id: q.awarded_marks
            for q in correct_paper(
                case.mark_scheme, old_answers, gemini_client=client
            ).questions
        }
        new_marks = {
            q.question_id: q.awarded_marks
            for q in correct_paper(
                case.mark_scheme, new_answers, gemini_client=client
            ).questions
        }

        for qid, gt in case.ground_truth.items():
            per_case.append(
                {
                    "paper_id": case.paper_id,
                    "fixture_variant": case.fixture_variant,
                    "question_id": qid,
                    "truth_marks": gt.awarded_marks,
                    "old_id_matched": qid in old_ids,
                    "new_id_matched": qid in new_ids,
                    "old_predicted": old_marks.get(qid),
                    "new_predicted": new_marks.get(qid),
                }
            )

        spent = client._ledger.total() - spend_before
        if spent > STOP_AND_ASK_USD:
            print(
                f"STOP-AND-ASK TRIPPED at ${spent:.6f} > ${STOP_AND_ASK_USD:.2f} "
                f"after {case.paper_id}. Aborting; partial results written.",
                file=sys.stderr,
            )
            break

    # --- metrics ------------------------------------------------------------
    n = len(per_case)
    old_matched = sum(1 for r in per_case if r["old_id_matched"])
    new_matched = sum(1 for r in per_case if r["new_id_matched"])

    # McNemar over mark-correctness, paired per leaf.
    old_correct = [r["old_predicted"] == r["truth_marks"] for r in per_case]
    new_correct = [r["new_predicted"] == r["truth_marks"] for r in per_case]
    b = sum(1 for o, nw in zip(old_correct, new_correct, strict=True) if o and not nw)
    c = sum(1 for o, nw in zip(old_correct, new_correct, strict=True) if nw and not o)

    spend_after = client._ledger.total()
    payload = {
        "label": "sweep37",
        "issue": 37,
        "authorised_by": "A5, inbox 2026-08-25T14:24:52",
        "cache_mode": "bypass",
        "design": "extraction run ONCE per case; both normalisers over the identical raw extraction; paired",
        "leaves": n,
        "id_positional_fallback_fires": total_fallback_fires,
        "id_match_rate_old": round(old_matched / n, 4) if n else None,
        "id_match_rate_new": round(new_matched / n, 4) if n else None,
        "id_match_rate_target_current": 0.99,
        "mark_correct_old": sum(old_correct),
        "mark_correct_new": sum(new_correct),
        "mcnemar_b_old_only": b,
        "mcnemar_c_new_only": c,
        "mcnemar_discordant": b + c,
        "spend_usd_before": round(spend_before, 6),
        "spend_usd_after": round(spend_after, 6),
        "spend_usd_delta": round(spend_after - spend_before, 6),
        "records": per_case,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"leaves={n}  fallback_fires={total_fallback_fires}")
    print(f"id_match_rate  old={payload['id_match_rate_old']}  new={payload['id_match_rate_new']}")
    print(f"mark_correct   old={sum(old_correct)}  new={sum(new_correct)}")
    print(f"McNemar discordant b={b} c={c}")
    print(f"spend delta = ${spend_after - spend_before:.6f} (ledger {spend_after:.6f})")


if __name__ == "__main__":
    main()
