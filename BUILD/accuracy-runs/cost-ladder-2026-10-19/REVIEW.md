# Cost ladder 2026-10-19: adversarial review of the measurement claims

Reviewer: accuracy-reviewer. Read-only, $0, no API calls. I recomputed every number from
`records.jsonl` / `results.json` / `summary.json` with throwaway scripts in /tmp. I ran
`judge()` from `.claude/worktrees/cost-ladder-run/lemely/accuracy/cost_ladder/gate.py`
and read the gate and runner code at HEAD (ff738929).

Verdict key: CONFIRMED (recomputed and it matches), CORRECTED (the right number is given),
UNSUPPORTED (the run files do not back the claim).

## Honest headline (use this in the final report)

> On the 12-case dev screen, the shipped stack (B1 + B12 + A1-Haiku) costs $0.0280 per
> script at 2027 rates. The clean all-live A/A reference is $0.1224, so the stack saves
> **about 77%** (75% for flash-lite). The 82.3% figure is measured against a rung-0
> baseline that is inflated by one runaway call. Nearly all of the saving comes from two
> levers. **B1** (binder second read, thinking medium to low) cuts the binder read from about
> $0.074 to $0.013 per script. **A1** (correction model) cuts correction from about $0.033 to
> $0.006–0.007 per script. **B12 (output cap) saved nothing measurable.** The cap was never
> approached (largest output 1,608 tokens against a 16,384 cap). Its reported 39.4% is the
> baseline's one-off 65,522-token runaway not happening again. B12 can stay as insurance
> against runaways, but it should not be credited with a saving. Mark accuracy did not
> move: across same-config reruns, 0 or 1 of 78 parts changed prediction, and no lever added
> a mismark. However, **A1-Haiku raises the teacher-review rate from 0–1/78 to 16/78
> (20.5%)**, and the cost gate does not measure review rate. Haiku's $ edge over flash-lite
> ($0.0280 vs $0.0302) is within run-to-run noise. It also rests on a Haiku 5.5 price row
> ($0.10/$0.50 per 1M) that I could not independently source. At Haiku-4.5 list prices
> Haiku would cost $0.053 per script, not $0.028. The Phase A ">=50% from rung 0" stop
> holds under every correction made here.

## 1. Verdicts recompute from summaries via judge(aa_floor=1, rung-0 p95)

| run | saving | tier | extra / allowed | pass | status |
|---|---|---|---|---|---|
| B1 | 0.36377 | big | 0 / 2 | yes | CONFIRMED (bit-identical) |
| B12 | 0.39376 | big | 0 / 2 | yes | CONFIRMED arithmetic. Attribution CORRECTED in §2a |
| A1 flash-lite | 0.50505 | big | 0 / 2 | yes | CONFIRMED arithmetic. Attribution CORRECTED in §6 |
| A1 Haiku | 0.54096 | big | 0 / 2 | yes | CONFIRMED arithmetic. Attribution CORRECTED in §6 |

I also recomputed each summary's `usd_per_script_mean`, `_now`, `latency_p95_ms` and
`validity_rate` from the records, composed with the baseline's non-live tags as
`compose_records` does. All match to 1e-6. The stored verdicts are the gate's honest output.
The problems are in what the inputs measure, not in the arithmetic.

`allowed_extra = 2` comes from ceil(0.02 × 78). The constraints file's worked example says
"the 2% term is 1 on cost-201's 31 scored parts". This screen scores 78 parts (31
distinct paper/question ids over 12 fixture variants), so the term doubled to 2. The
formula is applied as written and the point is moot because extra = 0 everywhere. The doc
example is stale (NIT).

## 2. Composition honesty

### 2a. B12's 39.4% saving: CORRECTED to about -1% to -3% (indistinguishable from 0)

- Rung 0 contains one extraction call on `0606_s23_qp_12_theory/wrong`: 65,522 output
  tokens, 369.7 s, parse_ok=False, **$0.4976** at 2027 rates. A retry followed it
  ($0.0138, 987 tokens).
- In B1, extraction is frozen, so B1's composed cost carries the runaway:
  extraction $0.6503 over 12 cases.
- In B12, extraction went live. Live extraction across 12 cases cost $0.1692 and no runaway
  recurred.
- Component totals, B1 composed vs B12 live (12 cases, 2027 rates):
  - extraction: 0.6503 → 0.1692
  - binder second read: 0.1525 → 0.1627 (B12 is *higher*)
  - correction: 0.4050 → 0.4004
- The cap was never hit. Max output tokens in B12 were 1,608 (extraction) and 1,604
  (binder), against the 16,384 cap. Under B1's thinking=low, binder thinking tokens are 0.
- B1 composed with the runaway removed is $0.05918, so B12 at $0.06102 is a **-3.1%**
  "saving". Also adding the whitespace case's extraction (which B1's composition lacks; see
  2b) gives $0.06026, a **-1.3%** saving.
- Conclusion: 100% of B12's measured saving is the runaway not recurring. 0% is the cap.
  What the cap is worth is an expected value: P(runaway) × (cost of a runaway minus the cost
  of a capped one, about 0.25 × $0.50). This screen shows 1 runaway in 48 live 3.8-flash
  extraction calls (baseline, A/A, B12, two A1s). That is roughly $0.0008 per script, about
  1% of rung 0, which is close to the 5% expected.

### 2b. Baseline whitespace case: 10 in-run cache hits worth $0. CONFIRMED distortion, quantified

- `0580_s23_qp_22_theory/whitespace` has 0 records in rung 0. All 9 of its calls replayed
  entries from the `correct` case. Its cost is $0.000; the same case costs $0.2003 in the
  A/A run. One correction call in `0625_s20_qp_31_theory/partial` was also a hit.
- Effect: the rung-0 mean is understated by about $0.0167 per script. The runaway overstates
  it by $0.0415 per script. Net, rung 0 ($0.1582) is about $0.025 above a clean baseline
  ($0.1334: runaway removed, whitespace filled from A/A).
- Effect on each saving:
  - B1 vs rung 0: the whitespace case is $0 in the baseline but $0.043 in B1. The runaway
    sits in both numerator and denominator. Both distortions work *against* B1, so **B1's
    36.4% is understated**. Clean B1 vs clean baseline is about 55% (CORRECTED).
  - B12 vs B1: B1's composition lacks whitespace extraction ($0.0136), a 1-point bias
    against B12. It is swamped by 2a.
  - A1 vs B12: both are fully live with 0 cache hits, so there is no distortion.
  - Final vs rung 0: flatters the final by about 5 points (see 2c).

### 2c. "Final vs baseline 82.3% (2027) / 80.4% (now)": CORRECTED

| reference | $/script (2027) | Haiku final saving | flash-lite final saving |
|---|---|---|---|
| rung 0 as reported | 0.1582 | 82.3% | 80.9% |
| rung 0 cleaned (no runaway, whitespace from A/A) | 0.1334 | 79.0% | 77.4% |
| **A/A, all live, no runaway** | **0.1224** | **77.1%** | **75.3%** |

At current (2026) rates, the final vs A/A is 74.7%, not 80.4%. Use the A/A figure: it is the
only reference measured with every call live and no anomaly. The cleaned rung 0 is a
reconstruction.

## 3. Latency gate: CONFIRMED, no lever would have failed against the A/A p95

- Rung-0 p95 is 493,044 ms. It is the runaway case, and `P95_RANK` with nearest rank on 12
  cases is the **max**. The A/A p95 is 264,586 ms, so the 2× limit would be 529,172 ms.
- Candidate p95s: B1 409,009 (this too is the frozen runaway case; B1's next-highest case is
  51,465), B12 57,260, flash-lite 58,463, Haiku 67,568. Every candidate passes against
  either reference. I re-ran `judge()` with the A/A p95 and all four pass.
- Caveat (SHOULD-FIX): "p95" here is the per-case **sum of call latencies**. It is not wall
  clock (corrections may run concurrently), and with 12 cases it is the maximum, not a
  percentile. The report should call it "max summed call latency per script".

## 4. Accuracy claims

Recomputed from `results.json`:

| run | scored | mismarks | abs mark error | needs_teacher_review | id-match | funnel ext/leaves/marked/matched |
|---|---|---|---|---|---|---|
| baseline | 78 | 7 | 8 | 1 | 1.0 | 78/78/78/78 |
| A/A | 78 | 6 | 6 | 1 | 1.0 | 78/78/78/78 |
| B1 | 78 | 6 | 6 | 0 | 1.0 | 78/78/78/78 |
| B12 | 78 | 6 | 6 | 1 | 1.0 | 78/78/78/78 |
| A1 flash-lite | 78 | 6 | 6 | 0 | 1.0 | 78/78/78/78 |
| A1 Haiku | 78 | 5 | 5 | **16** | 1.0 | 78/78/78/78 |

- Prediction changes (any part whose predicted mark differs):
  - baseline→A/A: 1 (0625/correct/11b, 1→3)
  - baseline→B1: 1 (the same part, fixed)
  - B1→B12: 0
  - B12→flash-lite: 0
  - B12→Haiku: 1 (0606/wrong/3b, 1→0, fixed)
  - New mismarks vs the stacked-on run: 0 for every lever. New mismarks vs rung 0: 0 for
    every lever.
- id-match and scored parts: CONFIRMED (1.0 and 78 in every run). No denominator narrowing;
  the funnel is complete in every run.
- "0 extra mismarks": CONFIRMED as a fact, with limited power. Five of the six persistent
  mismarks are one block that every run gets wrong identically (0580/partial
  2/4/12a/14/19, predicted 0 vs truth 1). That pattern suggests a fixture or truth-label
  issue, not marking noise. So the screen discriminates on about 73 parts. Those parts are
  correlated across fixture variants of 4 papers (31 distinct questions). 0 regressions out
  of 78 bounds the per-part regression rate at about 3.8% (rule of three). Per distinct
  question the bound is closer to 10%. It cannot detect a regression rarer than that.
- Haiku's one "fixed" part (3b) equals the A/A floor of 1. **It is not evidence that Haiku
  is more accurate (UNSUPPORTED if claimed).**
- **MUST-FIX for the report: the A1-Haiku review-rate regression is invisible to the cost
  gate.** Haiku flags 16 of 78 parts (20.5%) for teacher review. 15 are "confidence
  0.85–0.88 below review threshold 0.90". Every other run flags 0 or 1. The programme gate
  is review_rate_total <= 10%, and Haiku's confidences are on a different scale (0.82–1.0,
  mode 0.85/0.90) from Gemini's (0.95–1.0). The flags are informative: they catch 4 of the
  5 persistent mismarks, and `flag_recall` is 0.8. But each one costs a teacher review, and
  `judge()` checks no review-rate condition. This also drives Haiku's 7 borderline calls
  and 3 Gemini escalation calls ($0.0032 per script).
- Note: baseline (git 93a1764c) and A/A (f224a4b3) ran different commits with identical
  params_fingerprint. Rung 0 was resummarised under the 2026-10-19 user decision on
  recovered parse failures. Its `incomplete_before` lists 0606/wrong, which is the runaway
  case. Both facts are recorded. NIT.

## 5. Spend

- Ledger: Gemini $3.06170, Anthropic $0.03348.
- Sum of the six `run_cost.json` files: Gemini $2.71269, Anthropic $0.03348.
- **Gemini $0.34902 (11.4% of the ledger) is UNSUPPORTED.** No run directory, archive
  (`_archive_ladder` output) or log in this out-dir accounts for it. A plausible source is a
  pre-restart baseline on the voided digest, since `--restart-baseline` keeps the ledger.
  The report must name it, not leave it implied.
- Ledger total stays under both caps ($6 / $40).
- The ledger prices calls with the repo's own price table. It is not a provider invoice, so
  "billed dollars" means computed dollars.

## 6. A1 Haiku vs flash-lite ($0.0280 vs $0.0302): UNSUPPORTED as a real difference

- Correction side per script: flash-lite $0.00740. Haiku $0.00599, of which $0.00320 is
  3 Gemini escalation calls; Haiku's own calls are $0.00279. The difference is $0.0014.
- Upstream (extraction + binder) per script, for an identical config across three runs:
  B12 $0.02765, flash-lite $0.02280, Haiku $0.02202. The spread is $0.0056, 2.5× the
  $0.0022 Haiku–flash-lite gap. Escalations are discrete: ±1 escalation is about ±$0.0011
  per script.
- The A1 savings themselves include this upstream noise. Correction-only savings vs B12 are
  **42.6% (flash-lite) and 44.9% (Haiku)**, against the reported 50.5% / 54.1% (CORRECTED).
  The remaining 8–9 points are the A1 runs' upstream calls coming in cheaper under an
  unchanged config.
- Price row: `lemely/io/gemini.py:136,147` prices `claude-haiku-5-5` at $0.10 in /
  $0.01 cache read / $0.50 out per 1M. The comment confirms the **model id** against the
  docs, not the price. The bundled Claude API reference (cached 2026-09-25) has no Haiku 5.5
  row; its current Haiku is 4.5 at $1/$5. At $1/$0.10/$5, Haiku's correction calls cost
  $0.335 instead of $0.033, and the final becomes **$0.0531 per script, 76% more than
  flash-lite**. The choice of Haiku over flash-lite therefore depends on a price that has
  to be sourced (UNSUPPORTED until it is). The cache-write premium is ignored, but that is
  negligible (about $0.0001).
- Tokenizers differ: Haiku used 368k input / 45k output tokens (22.6k thinking) for the
  same 77 correction-side calls, against flash-lite's 190k / 28k. Token counts are not
  comparable across providers, so only $ is.

## Claims not checked / not backed by run files

- "B2 <= 12% saving after B1" (LADDER.md stop reason): no B2 run exists in this out-dir.
  UNSUPPORTED by measurement. It is a user-shelving rationale, not a result.
- Gemini and flash-lite price rows were taken as given from the code comments. I could not
  verify them offline.

## How each check was done

| check | how |
|---|---|
| 1, 2a, 2b, 2c, 3, 5, 6 | Ran: recomputed from records/results; `judge()` re-run with both rung-0 and A/A p95 |
| 4 | Ran: mismark sets, abs error, prediction churn, review counts, confidence histograms from `results.json` |
| Composition semantics, p95 definition, frozen-upstream rules | Read: `runner.py` (`compose_records`, `_summarise_marking`, `_nearest_rank`, `run_screen`) and `gate.py` at HEAD |
| Haiku price | Read: `lemely/io/gemini.py` price table; cross-checked against the bundled Claude API model table (no Haiku 5.5 row) |
