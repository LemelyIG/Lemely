# settle-58-q11b-2026-08-26 — did the reorder violation on q11b reproduce?

Authorised by inbox **B6** (2026-08-26T14:12:38+03:00), ~$0.01. Preflight posted
to #58 before any spend. **Actual spend $0.013608** against a $0.0156 central
projection and a $0.040 in-process brake (never approached). Ledger for this
worktree 2.720069 → **2.733677**; programme-wide sum (DA11) 3.124540 → **3.138147**.

## Result

| arm | awarded_marks over 10 repeats | ≥2 marks |
|---|---|---|
| unperturbed | `1 1 1 1 1 1 1 1 1 1` | **0/10** |
| perturbed (`p1,p2,p3 → p3,p2,p1`) | `1 2 1 1 1 1 1 1 1 2` | **2/10** |

Ground truth for this leaf is **1 mark**. Every call was `cache_hit=False`;
20 calls, exactly as the preflight said it must be.

**Pre-committed primary test: two-sided Fisher exact on [arm × (marks ≥ 2)],
α = 0.05 → p = 0.4737. NOT SIGNIFICANT.**

## What that does and does not license

**The violation reproduced.** Two of ten fresh perturbed repeats awarded 2
marks where ground truth is 1 — the same 1 → 2 the original
`metamorphic-58-2026-08-25` run recorded. It is not a one-off artefact of a
single call.

**Same-input churn on this leaf is zero, not small.** The unperturbed arm
returned 1 mark ten times out of ten. Pooling every other unperturbed marking
of this exact leaf that already exists on disk — `control-58-2026-08-25`
(`pass_a` = `pass_b` = 1) and the two baseline arms inside
`metamorphic-58-2026-08-25` (reorder baseline 1, rename baseline 1) — gives
**0/14**. So the "it is just gemini churn" explanation, which the earlier
control arm could only reject corpus-wide, is now rejected on this leaf
specifically.

**And it still is not significant.** Post-hoc pooling of every perturbed
observation (this run's 2/10 plus the original violation) against every
unperturbed one gives **3/11 vs 0/14, Fisher p = 0.0717** — closer, still above
α, and *post-hoc*, so it is reported as secondary and never as the finding.

At the observed ~20% effect size, significance would need roughly **n = 25 per
arm** (2/10 → p = 0.47; 5/25 → p = 0.050; 8/40 → p = 0.005). **This run will
not be re-run at higher n.** MISSION §12.9 forbids exactly that move, and the
design was authorised at ~10 per arm knowing what 10 could resolve.

## Verdict, in the pre-committed vocabulary

Of the three outcomes named in the preflight before the data existed, the
result is closest to **(2) — no significant difference** — but it is not
outcome 2 as written, and saying so matters: outcome 2 assumed *both* arms
would vary. Only the perturbed arm varies. The honest statement is:

> The reorder violation on `0625_s20_qp_31_theory_partial` q11b **reproduces**
> (2/10) against **zero** same-input variation on the same leaf (0/14), which
> is directionally what a real order-sensitivity defect looks like — but at
> n = 10 per arm the pre-committed test does not reach significance, so it is
> **not established** as a marker defect and must not be reported as one.

## What was verified rather than assumed

- **Which of the three variants.** The metamorphic report records only
  `paper_id`, which all three `0625_s20_qp_31_theory` fixtures share (DA6 keys
  a leaf on `(paper_id, question_id)`; the variant directory is not in the
  key). Identified as `_partial` from the outcomes-list position, then
  **independently confirmed by the mark values**: the three variants' q11b
  score 3 / 1 / 0, and the violated record's `baseline_marks` is 1.
- **That marking q11b alone is the same experiment.** `correct_paper` builds
  `sibling_prior` only when `q.parent_id is not None`
  (`lemely/io/correction_ai.py:639-645`), and q11b's `parent_id` is `None`, so
  its prompt is byte-identical whether the scheme holds seven leaves or one.
  Had it had a parent, the restriction would have changed the input and this
  design would have been illegitimate.
- **That the call count could not multiply.** `mark_question` adds a thinking
  retry only if `thinking_budget_for['correction_borderline'] > 0` (key absent)
  and a Pro escalation only if `escalation_model` is set (`None`). The script
  refuses to run if either becomes true.
- **That the perturbation was real.** `p1,p2,p3 → p3,p2,p1`, asserted before
  the first call; a no-op permutation would have made the two arms identical.
