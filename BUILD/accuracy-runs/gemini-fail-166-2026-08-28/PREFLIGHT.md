# #166 preflight — ruling C22 authorises ~$0.15 to reproduce one 0606 failure with logging

**Ceiling for this run: $0.15.** Programme ledger before: **$5.993470** against
the committed **$8.00** (headroom $2.006530). MISSION §10a requires the unit and
the population stated before any spend.

- **Unit: one Gemini `parse_mark_scheme` call on one PDF.** Not per paper, not
  per page. The measured per-call figures on this exact task in the C20 sweep
  ranged **$0.046–$0.21**, so one scheme with one retry fits inside $0.15 and
  two retries may not. The run stops on the ledger, not on an estimate — the
  same control C20 proved.
- **Population: the schemes det cannot parse AND Gemini failed on.** This is the
  number that moved, and it moved before any money was spent.

## Step 1, zero spend: the population changed under the issue

#136 (PR #169) landed between #166 being opened and this authorisation. It fixes
four det mark-total defects, so schemes that previously escalated may now parse —
in which case they never reach the Gemini path at all and are not #166's problem.

Re-checked all **12** schemes the C20 sweep recorded as Gemini-parse failures,
with `escalate_on_mark_mismatch` at its **default True**, which is what decides
"det fails outright":

| scheme | det now | note |
|---|---|---|
| `0606_s23_ms_11` | **PARSES 80/80** | leaves the population |
| `0625_m20_ms_32` | **PARSES 80/80** | leaves the population |
| `0625_s23_ms_41` | **PARSES 80/80** | leaves the population |
| `0606_m20_ms_12` | fails +20 | |
| `0606_m21_ms_22` | fails +9 | |
| `0606_w19_ms_22` | fails +22 | |
| `0580_s21_ms_23` | fails −37 | |
| `0580_s23_ms_41` | fails −75 | |
| `0625_s19_ms_53` | fails +1 | |
| `0625_s25_ms_42` | fails −1 | |
| `0625_w19_ms_52` | fails +3 | |
| `0625_w19_ms_61` | fails +1 | |

**3 of the 12 no longer need the Gemini path at all.** So #166's headline —
*"0606 fails 0 of 4"* — is now **0 of 3**, and the 50% figure was measured over a
population that has since shrunk by a quarter.

**This does not repair the finding.** The remaining nine still failed the Gemini
parse, 0606 is still 0 for 3, and the size correlation is untouched. What it does
is stop the diagnosis being run against a scheme that no longer belongs to the
problem — `0606_s23_ms_11` was a live candidate for this probe and would have
been a wasted call.

**Chosen target: `0606_m21_ms_22`.** It is still a det failure, it is 0606, and
it is the scheme the C20 n=1 probe already ran — so its cost is *measured*
($0.099146 failing, $0.076435 succeeding) rather than estimated, and it is the
one scheme known to be **non-deterministic** across attempts. That last property
is what makes it the right target: a single reproduction of a deterministic
failure proves less than one of a flaky one.
