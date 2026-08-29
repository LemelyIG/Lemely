# §13 clause 5 — Gemini marking accuracy, measured in its own terms

**Zero spend.** Computed from `aa-floor-2026-08-23-a`'s per-repeat records, which
already carry `parse_path`. No new run.

Clause 5 requires **both paths measured in their own terms**: det **parse
coverage** — now **331 of 479** (DA34/DA39/DA41) — and **Gemini marking
accuracy**. The det half was measured this session. This is the other half.

## Method validated before use

The leaf collapse here (a leaf counts correct iff **every** one of its
fixture-variant rows is correct) **reproduces the published
`wilson_mark_accuracy_per_repeat` successes exactly on all 10 repeats** —
23/24/24/21/24/23/24/25/24/23. The script asserts this and refuses to run if it
ever stops holding. Only then is the same collapse split by path.

`parse_path` tracks the marking path exactly as C11 describes: `det` is the MCQ
paper alone, `gemini` is all four theory papers.

## The result

| path | leaves | correct (mean of 10 repeats) | accuracy | 95% Wilson at the honest n |
|---|---|---|---|---|
| **det** | 8 | 8.0 / 8 | **100%** | **67.6% – 100%** (±16.2pp) |
| **gemini** | 23 | 15.5 / 23 | **69.6%** | **49.1% – 84.4%** (±17.6pp) |

## Three things this says

**1. The published headline blends a 100% path with a 70% path.** Leaf accuracy
on the golden corpus is ~77.4%; that is a mixture, and the mixture weight is an
artefact of the fixture set (8 MCQ leaves against 23 theory leaves), not of the
production corpus.

**And the weighting is backwards relative to what matters.** Per C11/DA23, MCQ
schemes carry **zero** `answer_points`; the Gemini path carries **10,314 of
10,314**. So the path responsible for every answer point in the corpus is the one
measuring **69.6%**, and the headline is pulled upward by a path that carries
none of them.

**2. det's 100% is not evidence the det marking path is perfect.** It is 8 MCQ
leaves from a single paper, and its own Wilson lower bound is **67.6%** — the
interval at n=8 is almost as wide as gemini's at n=23. A point estimate of 100%
with that interval supports very little.

**3. Pooling the repeats would fake the precision.** The 10 repeats re-mark the
**same** 31 leaves under an identical fingerprint, so they are not independent
observations. Pooling would report **±6.0pp** for gemini and **±2.3pp** for det
instead of **±17.6pp** and **±16.2pp**. Both are in the artifact so the
difference is visible rather than assumed away — **the naive figures are recorded
to be refused, not used.**

## Clause 5 status: measured, NOT to scope

Clause 5 asks for Gemini marking accuracy *"which covers 10,314 of 10,314 answer
points"*. **This measures it on 23 distinct leaves of one golden corpus**, at
±17.6pp. That is a real figure and it is not the required one.

**So the honest clause-5 position is: det parse coverage MET; Gemini marking
accuracy MEASURED BUT OUT OF SCOPE**, and closing the gap needs the labelled
corpus (#47) rather than more analysis of this one — the same shape as clause 3's
`NOT_APPLICABLE` verdict, which the mission accepts as published-in-the-negative.
