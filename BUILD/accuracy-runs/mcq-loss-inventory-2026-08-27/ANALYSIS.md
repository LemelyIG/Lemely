# MCQ loss inventory — #94, 2026-08-27

Det-only, **$0.00, zero Gemini calls.** 479 mark schemes opened; **80 are
MCQ-typed** (the only papers `mcq.py` runs on); 399 non-MCQ skipped; **0
unreadable**.

## Result

| | |
|---|---|
| MCQ papers inventoried | **80** |
| papers with a discarded table | **1** |
| papers with a question shortfall | **1** |
| shortfall the discards account for | **1 of 1** |
| distinct disqualifying values corpus-wide | **1** — `QUESTION DISCOUNTED` |
| questions parsed | **40** on 79 papers, **12** on one |

The single affected paper is **`0625_s24_ms_21`**: 40 expected, 12 parsed,
**28 lost**, all of them in one 29-row table discarded because column 3 held
one cell reading `QUESTION DISCOUNTED`.

## Read this honestly: the defect is real, confirmed, and RARE

#94 was opened on the strength of one paper and the reasonable worry that it
represented a class. **It does — a class of exactly one, in this corpus.**
79 of 80 MCQ papers parse all 40 questions with nothing discarded.

That is not an argument that the instrumentation was wasted. It is the opposite:
the only way to know the prevalence was to count it, and before this the answer
was unknown rather than small. But it does mean **the repair (#94 scopes the fix
out) is a one-paper repair on today's corpus**, and nobody should size it as
though 28-question losses were widespread.

## Two premises corrected by measurement

**1. The FACT of this loss was never silent.** `reconcile` compares the parsed
mark total against the cover page's `maximum_mark` and logs
`mark_total_mismatch_escalating` (or `…_warning` when escalation is off).
Re-parsing `0625_s24_ms_21` with today's code raises
`ParseError: parsed 12, expected 40 (discrepancy 28 > tolerance 0)`. #94's
premise — *"a scheme that yields 12 questions instead of 40 looks identical to
one that legitimately has 12"* — does not hold on the MCQ path, and probably
stopped holding when #93 landed and this paper started being typed MCQ at all.

What **was** silent is the **mechanism**. Nothing said a 29-row table had been
thrown away, or why. "This paper failed" is a census bucket; "one withdrawn
question disqualified its whole answer column" is a work order.

**2. `rows_discarded_in_kept_tables` is 2 on 79 papers and must not be read as
loss.** Those are the header rows of the two tables each paper has (the lossy
paper has 1, because it only kept one table). No paper anywhere in the corpus
discards more than 2. The counter is worth keeping — it covers a path the
reconciler cannot see at all — but its baseline is 2, not 0.

## What the reconciler still cannot see, and this can

- It compares **marks**, not question counts. On MCQ they coincide only because
  every question carries one mark; a drop compensated by an overcount elsewhere
  nets out of the mark comparison while still losing questions.
- It says nothing about rows dropped **inside** a table it accepted.
- It needs `maximum_mark` to have been extracted. Where that fails, the mark
  comparison cannot run at all; the table/row counters still can.
