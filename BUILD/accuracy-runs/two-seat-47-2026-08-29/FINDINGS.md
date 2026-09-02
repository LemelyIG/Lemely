# #47 designed for two seats (C24) — and the second seat's sample is undersized for its stated job

**Zero spend.** Pure arithmetic on figures already fixed by #47 and #51, plus a
source read of the labelling machinery.

## First, the good news: the machinery is already two-seat capable

C24 required #47's protocol to be built for two independent seats from the
outset. Checked at source rather than assumed — most of it already is:

- **`labeller_id` is server-bound**, stamped onto every payload before writing
  and *never* taken from the client (`records.py:130-160`).
- **Storage is per `(paper_id, pass)`, not per labeller**, so two labellers on
  one paper interleave in the same hash chain and stay individually
  attributable (`records.py` docstring, `paths.py`).
- **Manifests are per `(paper_id, labeller_id)`** — filename-scoped, so seats do
  not overwrite each other (`paths.py:65`).
- **Cross-labeller blindness is already tested**:
  `test_pass2_context_for_a_different_labeller_does_not_see_labeller_a`.
- **Per-mark-point agreement exists** (`mark_point_verdicts`, `agreement_wilson`)
  from #105/B12.

So "design for two seats" is **not** a rewrite. What follows is the part that is
not settled.

## The finding: at 10%, H7 cannot do what H7 exists to do

#51 states H7's purpose plainly — without inter-annotator agreement *"there is no
ceiling on how good the pipeline can honestly be said to be"* — and fixes the
sample at **10% of labelled leaves**. #47 targets **≥300 distinct leaves**. So
the double-labelled overlap is **30 leaves**.

**A ceiling is only useful if it is measured at least as precisely as the thing
it bounds.** Both intervals, 95% Wilson, recomputed rather than quoted:

| quantity | n | interval | half-width |
|---|---|---|---|
| pipeline accuracy at 83.8% (#47's own justification) | **300** | 79.1% – 87.4% | **±4.18pp** |
| H7 agreement, if A and B agree 90% of the time | **30** | **74.4% – 96.5%** | **±11.08pp** |
| H7 agreement, if they agree 95% | 30 | **78.7% – 98.2%** | ±9.74pp |
| H7 agreement, if they agree 100% (30/30) | 30 | 88.7% – 100% | ±5.68pp |

**The ceiling is measured 2.3×–3.3× less precisely than the accuracy it is meant
to bound.** And the consequence is sharper than "wide":

> **Unless labeller B agrees with A on all 30 of 30, H7's 95% lower bound sits
> BELOW the pipeline's own accuracy point estimate (83.7%).**

At 95% observed agreement the lower bound is **78.7%**; at 90% it is **74.4%**.
In either case the measurement is consistent with a human ceiling *lower than the
machine's measured accuracy* — which is not a ceiling, it is a shrug.

**What it would take to match ±4.2pp**, at each assumed agreement rate:

| assumed agreement | double-labelled leaves needed | share of a 300-leaf corpus |
|---|---|---|
| 80% | 346 | **115%** (impossible at n=300) |
| 85% | 276 | 92% |
| 90% | 195 | **65%** |
| 95% | 108 | 36% |
| 100% | 42 | 14% |

## Stated honestly, including against my own argument

- **Agreement and accuracy are different quantities**, so "match the precision"
  is a design *choice*, not a law. The comparison is offered because #51 itself
  frames H7 as bounding the accuracy figure.
- **The lower-bound comparison does not depend on that choice.** Whether or not
  the two intervals should match, an interval that admits values below the
  measured accuracy cannot establish a ceiling above it.
- **This is a cost decision about a human's time**, which is exactly why it is
  not an agent's to take: 195 leaves is roughly 5 papers of labeller B's work
  against the ~1–2 h #51 currently estimates.

## The decision this needs

1. **Accept 10% and restate H7's purpose** — a coarse sanity check that the two
   seats are not wildly divergent, *not* a ceiling. #51's "Why" would need
   rewriting, and every published accuracy figure would carry an agreement
   interval too wide to bound it.
2. **Raise the overlap** to whatever precision H7 is supposed to deliver — 65% of
   the corpus for ±4.2pp at 90% agreement.
3. **Keep 10% but pre-commit a decision rule** — e.g. treat H7 as passing only on
   30/30, the one case where the interval clears the accuracy estimate.

**No recommendation is offered**, and I should say why that is not modesty: every
option here spends someone else's hours, and option 1 is the one that costs the
programme nothing and me nothing — which is exactly the shape of recommendation
to distrust from an agent.

## What is NOT affected

The **sample rule** is already pre-committed in `eval/relabel_manifest.json` with
its salt in cleartext, and membership is deliberately not computed until #47
completes (DA2) so no labeller can know which leaves are watched. **Changing the
overlap share does not touch that guarantee** — the rule ranks all leaves and
takes a prefix; only the prefix length changes. It must be changed **before**
#47 completes, or the choice becomes visible to the sample.
