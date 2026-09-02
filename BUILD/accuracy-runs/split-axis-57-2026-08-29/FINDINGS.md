# #57 — DA1's parse-path axis is a CONSTANT over the corpus it partitions, not an empty stratum

**Zero spend.** Read from `corpus/manifest.json` and the 289 committed schemes.

## The finding, verified rather than inferred

DA1 stratifies on **syllabus code × parse path (det/Gemini) × tariff band**.

`corpus/manifest.json` records:

```
gemini_used: False
cost_usd:    0.0
totals:      {source_pdfs: 479, parsed: 289, failed: 190}
```

**Every one of the 289 committed schemes is det-parsed. There are zero
Gemini-parsed schemes in the population #57 is asked to partition.**

So the parse-path axis does not have *sparse* strata — it has **one level**. A
stratified split cannot stratify on a constant, and bullet 1 ("stratified split
proposed over the restored corpus") cannot be executed as DA1 specifies.

## This corrects a looser statement I posted earlier

A previous run recorded on this issue that *"the Gemini strata are empty because
#88's sweep aborted at 6 of 190"*. That is **not quite right, and the difference
matters.**

The aborted sweep's 6 schemes and C20's 12 were parsed into **staging
directories**, never into `corpus/`. They are not in the partitioned population,
so they would not populate the axis even if they were counted. **The corpus was
never Gemini-parsed at all** — `cost_usd: 0.0` is the proof, and it is a stronger
statement than "the sweep did not finish".

## What would populate the axis, and what stands in the way

Populating it is **#88** — Gemini-parse the schemes det cannot handle and commit
them. That is blocked by **#166**: the fallback fails on **~50%** of those
schemes and **100% of 0606** (DA35), so a completed sweep would deliver a
lopsided, partly-unfillable stratum rather than a balanced one.

**And the population shrank in a way that helps.** Det parse coverage went
**289 → 331 of 479** this session at zero cost (DA34/DA39/DA41), so the schemes
needing the Gemini path are **148, not 190**. The corpus has not been regenerated
at that revision, so `corpus/` still holds the 289.

## What this means for #57's three bullets

| bullet | status |
|---|---|
| 1. stratified split **proposed** | **CANNOT be executed as DA1 specifies** — one of the three axes does not vary in the population |
| 2. membership **frozen** and recorded | follows bullet 1 |
| 3. **human approval** recorded | #49, and C25 confirmed #49 is not a gate on #55 — but it is still this issue's bullet 3 |

## Three routes, and none is an agent's to choose

1. **Populate the axis** — regenerate `corpus/` at the current parser revision
   (289 → ~331 det) and Gemini-parse the remaining 148. Needs #166 resolved first,
   or it buys a stratum that is ~50% missing by construction.
2. **Change DA1** to stratify on the two axes that *do* vary — syllabus code ×
   tariff band — recording parse path as a **constant, with the reason**. DA1 was
   fixed in a human interview; **an agent must not re-derive it around an
   inconvenient measurement.**
3. **Wait**, and accept that #57 → #47 → #51 → #55 stay blocked.

**No recommendation.** Option 2 is the one that would let this issue proceed
today, which is exactly why it should not come from me: it changes the
measurement design to fit what the data currently supports.
