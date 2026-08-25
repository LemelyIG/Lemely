# control-58-2026-08-25 — what actually happened, including the mistake

## The mistake: this control ran TWICE, concurrently

The first copy was launched in the background. A `pgrep` check reported it gone
and `report.json` did not exist, so it was recorded as dead-without-output and a
second copy was started in the foreground. **The first copy was not dead.** Both
ran to completion, both wrote `report.json`, and both appended to `run.log` —
which is why `run.log` holds two complete summary blocks (lines 257-259 and
326-328) and why the two disagree on the ledger figure they each observed.

This is exactly the failure the state file's own protocol warns against ("POLL
THE LOG, DO NOT START A SECOND COPY"). The protocol was followed in intent and
still produced a double run, because absence of a process plus absence of an
output file was treated as proof of death. It is not: it is also what a live
process looks like between its last log flush and its write of `report.json`.

**Cost of the mistake: the control arm spent $0.287153 where one run costs
about $0.06.** That is still inside the ~$0.28 the directive authorised, but it
is inside it by accident, not by design.

## Do not trust `report.json`'s spend fields

`report.json` was written by whichever copy finished last. It reads
`spend_usd_before: 1.675386`, `spend_usd_after: 1.958713`,
`spend_usd_delta: 0.283327` — but that "delta" includes the *other* copy's
spend, because the two processes shared one ledger file. It is not the cost of
one control run.

`run.log`'s `usd_cost` lines sum to $0.238111, which is also wrong: two
processes appending to one file lost writes.

**The ledger is authoritative.** `outputs/gemini_spend.json` went
1.671560 -> 1.958713, so the true total for this control arm is **$0.287153**.
This is the direct evidence for the ledger-basis decision recorded in
DECISIONS.md.

## The science is unaffected — and stronger

Both copies scored the SAME 31 leaves (each computing `reorder_mark_points`'
own skip set) and both found **0 differing**. They were independent: 107 gemini
calls, `cache_hit=False` on every one, zero cache hits. So the two runs are two
independent replications of the same control, and combine:

| arm | result | Wilson 95% CI |
|---|---|---|
| control, same input twice (combined, 2 replications) | **0/62 differ** | [0.0%, 5.8%] |
| reorder_mark_points, perturbed | 1/31 violated | [0.6%, 16.2%] |

Fisher exact two-sided on the single-replication comparison (1/31 vs 0/31):
**p = 1.000**.

## What this settles, and what it does not

**Settled — the 0.1565 figure does not transfer to this design.** Under
p=0.1565 we would expect 4.9 differing leaves per 31; across 62 leaf-pairs we
observed 0. P(0 of 62 | p=0.1565) = 2.6e-05. The published 0.1565 was measured
end to end (extract+mark, transcription included); this design feeds
ground-truth answers straight in with no extraction step, so it measures
**marking-only** churn. There is no 0.1565 here to subtract.

**Not settled — the violation itself.** The control removes the pre-registered
"it is just gemini churn" explanation, but 1/31 against 0/62 at these n cannot
establish a reorder defect either. Underpowered, in both directions.

**The experiment that would settle it** is re-marking `0625_s20_qp_31_theory`
q11b ALONE, perturbed and unperturbed, ~10x each — roughly $0.01, because it is
one leaf. That is a **different design** from the one authorised, so it is
proposed on #58 and NOT run.
