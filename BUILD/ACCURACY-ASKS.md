# ACCURACY-ASKS.md — the open human decisions, in one place

**Status 2026-08-25: the programme is fully blocked on this list.** Seventeen
consecutive runs have found no decision-free work left. Every open issue is
triaged at source; none has zero comments. Nothing here is a request to do more
investigation — each row is a decision only the human can make.

**How to answer.** Reply on the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or append to
`BUILD/ACCURACY-INBOX.md`, naming the ask number and your choice — e.g.
`A1: retire`. Partial answers are useful: **A1 alone lands a finished, CI-green
PR.** Answering A8 then A5 unblocks the largest downstream chain.

Recommendations are the orchestrator's reading, offered so a decision is cheap.
They are not defaults — nothing here is acted on without an answer. Where a
recommendation would make a gated metric easier to hit, that is flagged, because
that is exactly the case where an agent's recommendation should not be trusted.

Source: each row was verified at its issue by the run that raised it; the
GitHub state below was re-verified 2026-08-25. Cost figures are corrected-basis
(ledger × the pre-M0.2 understatement factor) per MISSION §10 and §12.4.

Ledger: **$1.488057** of the $25.00 ceiling. Stop-and-ask sits at $20.00.

---

## A1 — #58 bullet 4: measure it (~$0.144) or retire it? **← unblocks a merge today**

**Blocked:** PR #90 (`feature/accuracy-58-...` → `develop`). **OPEN, MERGEABLE,
`mergeStateStatus=CLEAN`, all five CI checks SUCCESS** (test 3.12/3.13/3.14,
pre-commit, web). This is the only thing between it and merge.

**Question:** bullet 4 asks for a measured figure that costs ~$0.144 corrected.
Either authorise that spend, or formally retire the bullet the way #40's bullet 4
was retired on 2026-08-24 — recorded as **retired-unmet**, never as met.

**Recommendation:** retire, with the same explicit note #40 got. #58 is
label-free metamorphic tests; the bullet's figure is not load-bearing for any
other item. *Flagged: this is the cheaper branch, and it is the branch that
avoids a measurement. Authorising the $0.144 is entirely reasonable and well
inside headroom.*

## A2 — #88 q2: `profiles.py:50`

A paper-profile fix that **changes awarded marks** (gate-9 mark-changing under
the 2026-08-24 DOES-not-MILESTONE test), so it needs its own before/after sweep.
Left untouched pending your call. Same shape as the `mcq.py` finding in A4.

**Recommendation:** none offered — this is a marks-changing production change.

## A3 — #88 q1/q3: fall under H4 (#49)

Both reduce to frozen-split questions that #49 owns. #49 is an H issue: never
closed, resolved or worked around (MISSION §3.5). Needs you directly.

## A4 — #45: the three-option design question

The failure-reason census taxonomy. Options: (1) ship as-is; (2) ship now and
open instrumentation as its own issue; (3) instrument the parser first.

Evidence gathered since: `0625_s24_ms_21` loses **28 questions to a single cell**
— CAIE withdrew question 14, so `find_mcq_answer_col` (`lemely/io/det/mcq.py:23`)
requires *all* cells be A–D, returns `None`, and `parse_mcq_tables` skips the
whole table. Blast radius measured honestly: **1 of 479 schemes**, not the 3 a
grep suggests. The cause is invisible to aggregate arithmetic but unambiguous on
direct observation, and no current bucket names it — evidence that (3) pays.

The branch is reviewed-clean (two `accuracy-review` rounds, second returned
`merge`, zero findings), 38/38 tests green, `lemely/` diff **empty**. It is not
PR'd because the design question *is* the remaining work.

**Recommendation:** (2) — ship now, instrument as its own issue.

## A5 — #37: gate-9 authorisation, or a waiver on non-blindness grounds

**The instrument-blindness escape hatch is closed for #37.** Unlike #38, the
chain is live: `measure_accuracy(extract+mark)` → `grading.extract_answers` →
`GeminiAnswerExtractor.__call__` → `normalize_extracted_answers`, which has
exactly **one** production caller. A sweep here would be informative.

Also established, and it matters beyond #37: **`id_match` is a hard-coded
literal.** It is assigned by hand at `harness.py:402` (`"exact"`), `:788` and
`:817` (`"unmatched"`); `"fuzzy"` is never emitted. Worse, the positional
fallback (`answer_extraction.py:68-77`) **overwrites `question_id` with a genuine
manifest id**, so a guessed answer is stamped `"exact"` — the reassignment is
laundered. **Therefore `tests/golden/results/2026-08-22-f7be062.json` and
`-79f5fa8.json` (`records=71, id_match={'exact':71}`) are NOT evidence the
fallback never fired** — they are equally consistent with 0 and with all 71.
Do not cite either as a clean bill of health.

Bullet 3 is confirmed correct at source and the same-commit rule should **not**
be relaxed. Free when the sweep runs: count `id_positional_fallback` WARNING
lines to get the fire rate nobody has — in the *same* run, not a second sweep.

## A6 — #38 (a)/(b)/(c): the provably-blind gate 9

Gate 9's sweep for #38 is **null by construction**: the harness loads
pre-parsed `mark_scheme.json`, so the change cannot move the measured number.
Ruling needed on which of (a)/(b)/(c) applies before any re-run.

**Recommendation:** waive the sweep on instrument-blindness grounds — buying a
guaranteed-zero delta at full cost is not a measurement. *Flagged: this is a
recommendation to skip a gate. It rests on a structural claim you can check.*

## A7 — #38 bullet 2 needs re-stating

As written it is **harmful on 56% of affected papers**. Needs a new formulation
from you.

## A8 — #39 bullet 4 is not implementable as written **← answer before A9**

It depends on `is_excerpt`, which exists only at `harness.py:75` — a harness
attribute, not a property of the parsed scheme.

## A9 — #39: do NOT authorise gate-9 before A8 is settled

Not a new ask — a **hard ordering constraint**, posted on #39. The defect is
already baked into the fixtures:
`tests/golden/0625_s20_qp_31_theory_correct/mark_scheme.json` carries linearised
newlines on 11 of 19 answer points, including the verified `11b/p2
(64 × 240)/960 = 16` case. So a **post-load** normaliser would fire and a sweep
would measure it; a **parser-side** fix — the only technically correct one — is
invisible, because the fixtures keep their already-linearised text either way.

**Authorising the sweep before the design lands buys a guaranteed-zero delta at
full cost** if the fix goes parser-side. A8 and A9 are not independent.

## A10 — #39 bullet 5 re-stating; bullet 9 must NOT be loosened

Bullets 5 and 9 are **not jointly satisfiable** as written. Bullet 5 needs
re-stating; bullet 9 is the honest constraint and should hold.

## A11 — #39 bullet 6 is zero, not six

Measured: **zero PUA codepoints in 22,825**, against a bullet asserting six. The
bullet is factually wrong and needs re-stating or retiring.

## A12 — #59: three prerequisites, none established

Do real scans exist; is fetching them authorised; and where does the pairing
model live? #59 is not startable until all three are answered.

---

## Also standing

- **#41 bullet 2 is a MISSION §12.7 human call** (judgment on CAIE marking
  principles). Not startable without you.
- **#28 is CLOSED with every acceptance box unticked; the 2×2 still does not
  exist.** The forcing mechanism it was blocked on *did* land in PR #87
  (`harness.py:705-710` makes `arm` override `scan_path`; `cli.py:1013-1025`
  exposes `--arm`). Open question, recommended (a), **not acted on**: does a
  spend authorisation granted while an issue was OPEN survive it being CLOSED?
- **#27's A/A floor is ratified and published.** Do not re-run it, and do not
  re-run at higher n to chase significance (MISSION §12.9).
- **DA9a: do not arm the ratchet against 29.03%.** That is the *bottom* of the
  measured range (mean 32.58%, range 29.03–41.94% over 10 live repeats), so
  arming against it gates on a figure unchanged code exceeds 7 times in 10.
  Restate it distribution-aware first (#36).

## Answered and not to be re-litigated

Gate-9 scope is **per-item only for mark-changing items** (2026-08-24). Apply
the test to what the code *does*, not which milestone it sits in. #28's ablation
spend is authorised with the $20.00 stop-and-ask as its only ceiling. #36 takes
option A. #57 is unblocked via option A — MCQ schemes parse deterministically at
zero cost, do those first.
