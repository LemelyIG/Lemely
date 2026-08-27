# Costed preflight — ruling C6, "deterministic parsing for MCQ ONLY"

**Zero spend.** Every figure below is measured from committed files and the
local source PDFs. Ledger unmoved at **$3.138148** (re-summed across all four
worktree ledgers, never carried forward from the header).

Artifacts: `cost_c6.py`, `cost_c6.json`. Token model and rates are **unchanged**
from `preflight-88-2026-08-26/recost_88.py` so the two are directly comparable —
input `pages * 258 + 1500` per call, `$0.30/1M` in, `$2.50/1M` out.

**Model validated against the prior artifact:** re-running the #88 failing set
through this script reproduces #88's four scenarios to the cent
($4.92 / $5.70 / $6.82 / $7.26). The model is the same model, not a new one.

---

## 1. What C6 actually moves

| | schemes | answer points |
|---|---|---|
| theory_extended | 87 | 4,692 (45.5%) |
| **mcq — det KEEPS** | **79** | **0 (0.0%)** |
| theory_core | 73 | 3,649 (35.4%) |
| practical | 26 | 1,031 (10.0%) |
| alternative_practical | 24 | 942 (9.1%) |
| **total committed corpus** | **289** | **10,314** |

**MCQ schemes carry zero `answer_points`.** MCQ answers live in the separate
`mcq_answer` field. This is measured, and it reconciles exactly with #41's own
independent 10,314-point census.

So C6 does not retire *most* of the det marking path. It retires **all** of it:

- **210 of 289** committed schemes (72.7%) move to the paid Gemini path.
- **10,314 of 10,314** answer points (100%) move with them.
- The paid set goes **190 → 400** of the 479 source mark schemes; det is left
  with the 79 MCQ schemes, which contribute no answer points at all.

## 2. Cost

| | n | pages | per-scheme median | per-scheme mean | per-PAGE median | per-PAGE mean |
|---|---|---|---|---|---|---|
| **ONE-OFF** — the 210 schemes C6 moves | 210 | 1,762 (8.39/scheme) | $5.41 | $6.27 | $6.13 | **$6.52** |
| **RECURRING** — every future full rebuild | 400 | 3,729 (9.32/scheme) | $10.33 | $11.97 | $12.94 | **$13.79** |
| *today, for comparison (#88 item 2)* | 190 | 1,967 (10.35/scheme) | $4.92 | $5.70 | $6.82 | $7.26 |

The one-off and the recurring cost are reported separately because conflating
them is the trap. Only the first is a sweep. **The second is the commitment**:
once det no longer serves the non-MCQ population, every corpus rebuild from here
costs $10–$14 instead of $5–$7, permanently.

## 3. The ceiling — C6 as ruled cannot be executed without a ceiling decision

| | value | source |
|---|---|---|
| ledger, re-summed | **$3.138148** | four worktree `outputs/gemini_spend.json`, per DA11 |
| committed hard ceiling | **$8.00** | `lemely/runtime/config.py:111`, the **durable** value |
| local override | $25.00 | `lemely.toml:25` — **GITIGNORED**, DA13's hazard class |

Against the **committed $8.00** — the only value that survives worktree deletion
and the only one CI can see — headroom is **$4.861852**, and:

- the **one-off** alone lands the ledger at **$8.55–$9.66: BREACH**;
- the **recurring** rebuild breaches on its own, **every time it runs**.

Against the local $25.00 the one-off fits and the first recurring rebuild fits
($16.93 worst case); a second does not. But that $25.00 is exactly the kind of
gitignored, worktree-local figure DA13 and DA17 both warn about, and it is not
the programme's durable record of its own ceiling.

**MISSION §12.4 requires stop-and-ask on any spend that would take the ledger
past `total_usd_ceiling`.** On the committed value, C6 does. So C6 is not
executable as ruled without either raising the committed ceiling deliberately or
accepting the breach in writing.

## 4. What C6 costs beyond money

Stated plainly, because these do not show up in a dollar figure:

1. **#112, #110, #136 and #39 become dead work.** All four are defects in
   non-MCQ det parsing. #136's fix half — which ruling C2 explicitly sequences
   #38's re-measurement behind — would be repairing a code path about to be
   retired.
2. **#53 (M3, Parse-Path Parity and Mark-Scheme Fidelity) is voided.** There is
   no parity to measure once one of the two paths is gone.
3. **MISSION §2 and §14 both rest on the det path being measurable.** §14 names
   "a programme where every number improves but the det path never moves" as a
   programme failure. C6 goes further and removes the path, which makes the
   failure mode unobservable rather than fixed.
4. **The escalation work loses its subject.** #38's `escalate_on_defaulted_marks`
   exists to route *det* output to Gemini when the det marks are untrustworthy.
   If all non-MCQ output already goes to Gemini, the gate has nothing to gate.

## 5. The fork

C6 was ruled before any of the above was measured. Three ways forward:

- **(a) Proceed as ruled.** det → MCQ only. Requires a ceiling decision first
  (§3). Then close #112, #110, #136 and #39 as retired-by-C6 rather than leaving
  them to be picked up by a future run.
- **(b) Narrow C6 to the question #41 actually asked** — A-mark dependency is
  left undetermined on the det path, per ruling B1's own "may leave cases
  unresolved, accepted". The det path and all four fixes stay live. No new spend.
- **(c) The middle reading.** det keeps parsing everything (so #112/#110/#136/#39
  stay valuable), but det-parsed marks are trusted end-to-end for MCQ only, with
  non-MCQ marking escalated. Smaller blast radius than (a); still needs its own
  routing issue and a recurring-cost preflight.

**No recommendation is offered between (a) and (b)** — that is an architecture
and product call, not a measurement one. What the measurement does say is that
the choice is not the marginal one C6 looked like when it was taken: it is
100% of the det marking path and a permanent doubling of per-rebuild cost.
