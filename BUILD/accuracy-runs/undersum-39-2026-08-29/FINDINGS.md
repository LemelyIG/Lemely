# #39 bullets 1–3 — measured before implementing, and two of the three collapse

**Zero spend, det-only.** Measured over all 479 source schemes, 13,690 leaf
questions carrying answer points, with the same type exemptions
`Question.validate_mark_point_sum` itself applies.

## Bullet 1 — the invariant is correct, and it never runs

`Question.validate_mark_point_sum` already states the invariant as the
**filtered** sum, excluding `is_alternative` and `is_optional`. Bullet 1 is met
in form.

**What is not met is enforcement.** The validator is a
`model_validator(mode="after")`, so it fires on `model_validate` — and
`rows.py` assigns `marks` and `answer_points` **after** construction. Pydantic's
`revalidate_instances` defaults to `never`, so wrapping the mutated Question in a
`MarkScheme` does not re-check it either. Verified both ways:

- `Question.model_validate({...primary sum 2, marks 1...})` **raises**.
- Constructing a legal Question and then assigning `answer_points` **does not**.

**Measured consequence: 4 questions across the 479 source schemes reach output
in breach, unflagged** — e.g. `0606_s19_ms_13` question `11i`, tariff 1 against a
primary sum of 3.

Small in count. The point is that the invariant #39 asks for exists, is written
correctly, and is silent.

## Bullet 2 — the under-sum direction would fire ZERO times on the det path

| | |
|---|---|
| leaf questions with answer points | **13,690** |
| primary sum **equals** tariff | **13,668** |
| primary sum **under** tariff | **0** |
| primary sum **over** tariff | 4 |
| questions with no answer points at all | 135 |

**Zero, and not by luck.** `rows.py` derives `q.marks` from the filtered primary
sum whenever the question row carried answer text, so under-summing is
**impossible by construction** on this path. Adding the check would ship a gate
that cannot fire.

This is the same order-of-operations that `escalate_on_defaulted_marks` got
wrong in the other direction — there, a plausible gate turned out to fire on
44.4% of papers. Measuring first is cheap; both failure modes are expensive.

## Bullet 3 — bullets 2 and 3 are the same bullet

The under-sum direction only has meaning where the tariff is **not** derived from
the points — that is, on the **Gemini** path, which is precisely the missing
paper-level aggregate bullet 3 names. **Bullet 2 should be folded into bullet 3
rather than implemented separately.**

Worth noting from #166/DA35: Gemini's observed validation failures are the
**over** direction (`sum of primary mark points exceeds total marks`), already
caught by the shared validator — which does run there, because that path goes
through `model_validate`. The under direction on the Gemini path is
**unmeasured**, because output that fails validation never lands.

## What was implemented

A reporter in `reconcile.check`, **unarmed by default**
(`escalate_on_primary_sum_breach`). Arming routes the paper to the Gemini
fallback, which DA35 measured failing on ~50% of the schemes det cannot parse —
the same cost-and-coverage call as `escalate_on_duplicate_leaf_ids` and
`escalate_on_defaulted_marks`, and not one to take as a tidy-up.

**No under-sum check was added**, and no paper-level Gemini aggregate: the first
cannot fire, and the second is bullet 3's own scope with its own design
questions.
