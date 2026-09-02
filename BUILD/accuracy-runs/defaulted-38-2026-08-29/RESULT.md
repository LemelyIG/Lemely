# #38 bullets 2–3 / ruling C2 — the clean defaulted-mark rate

**Zero spend, det-only.** C2 (2026-08-27) deferred these bullets behind #136's
fix and required the trigger to be decided **against a clean rate**, because the
published figure was contaminated by DA21 mechanism (B). #136 landed (DA34), so
the deferral is discharged.

Both arms over the **same 397 papers**; the before arm imports a package copy
with `rows.py`/`marks.py` from the commit before #136.

| | contaminated | **clean** |
|---|---|---|
| papers carrying ≥1 defaulted point | 177 (**44.58%**) | **136 (34.26%)** |
| papers where **every** point is defaulted | **25** | **3** |
| answer points | 22,345 | 22,372 |
| points defaulted | 4,928 (**22.05%**) | **2,000 (8.94%)** |

**The contaminated figures reproduce the published ones** — 44.58% against the
report's 44.4%, 22.05% against 21.6%, the small gap being that the published
numbers came from a 60-PDF sample and these are the full 397. So the before arm
is measuring the same thing the report published, which is what makes the after
arm comparable.

## C2's premise was right, and the contamination was most of the signal

**Mechanism (B) accounted for 2,928 of 4,928 defaulted points — 59%.** Where the
marks column merged into the answer cell, the code arrived as trailing text,
`parse_marks_cell` saw nothing, and every such point defaulted. Those codes are
now recovered and are **not** flagged `marks_defaulted`, because a mark read from
the wrong column was still *read*, not minted.

**The sharpest movement is papers where every point defaulted: 25 → 3.** Those
were papers whose entire marks column merged into the answer text — the whole
paper minted, and the flag correctly said so, but the cause was the parser rather
than the paper.

## Deciding the trigger, which is what C2 asked for

**A bare defaulted-count is still the wrong trigger.** At 34.26%, arming it would
route a third of the det corpus to the Gemini fallback — which #166/DA35 measured
failing on ~50% of the schemes det cannot parse. The original objection stands at
the clean rate: **most defaults are still correct by luck**, since 1 is the right
value for every `B1`/`M1`/`A1`/`C1`.

**A candidate that the clean rate makes affordable for the first time:
"every point in the paper is defaulted" — now 3 of 397 (0.76%), down from 25.**
A paper where *no* mark was read is suspect in a way a paper with one minted mark
is not, and 3 papers is a cost the earlier figure could not have justified.

**This is a proposal, not an arming.** It routes papers to the same fallback as
`escalate_on_duplicate_leaf_ids` (#110) and `escalate_on_primary_sum_breach`
(#39), and all three should be decided together rather than one at a time — that
is a cost-and-coverage call, and it is the human's.

## What is NOT claimed

- **This does not tick bullet 2 or 3.** It supplies the clean rate C2 required
  *before* the trigger is decided; the decision itself is still owed.
- **The 59% attribution is arithmetic on the two arms**, not a per-point trace:
  it is the difference in defaulted counts, and mechanism (B) is the only change
  between the arms that touches `marks_defaulted`.
