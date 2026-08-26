# ACCURACY-ASKS.md — the open human decisions, in one place

**Status 2026-08-26 (run 33): the programme is again fully blocked on this
list.** The previous A1–A13 list was answered in full on 2026-08-25 and every
one of those answers has been acted on. What follows is what has accumulated
since, plus the items that came back with new evidence.

Nothing here is a request for more investigation — each row is a decision only
you can make. Where I have a recommendation I give it, and where a
recommendation of mine would be self-serving (cheaper, or avoids a
measurement) I say so.

**How to answer.** Reply on the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or append to
`BUILD/ACCURACY-INBOX.md`, naming the ask number and your choice — e.g.
`B5: metamorphic-only`. Partial answers are useful.

**If you answer only one: B1.** It is the only item holding a finished branch,
and it is a real marking-principles call rather than a process question.
**If you answer three: B1, B2, B4** — B2 alone unblocks the longest chain
(#88 → #57 → the parsed corpus).

---

## B1 — #41: which rule governs the A-mark "silent" case?

**Branch `feature/accuracy-41-…` @ `09314c7` is implemented, pushed, unmerged.**

Your A13 ruling said to drive the A-mark dependency from each paper's own
printed Generic Marking Principles, with strict M-then-A as the **fallback
only, never the primary rule**. Implemented — and then measured: **0 of 36**
parsed principle strings across the golden corpus mention M/A dependency at
all. CAIE Generic Marking Principles govern awarding *fairly and
consistently*; mark-code semantics are simply not written there.

So the prompt's "if, and only if, these principles are silent" escape clause
fires for **100% of papers**, the blanket rule stays operative, and on the
A-mark axis the diff does exactly what `VERSION = "4"` did.

Your ruling covers two cases; the corpus lives entirely in a third:

| case | A13 says | reality |
|---|---|---|
| principles parsed **and** speak to M/A | drive from them | **never happens** — 0/36 |
| principles **not** parsed | strict M-then-A | 5 fixtures |
| principles parsed but **silent** on M/A | *not addressed* | **100% of GMP papers** |

Any default for case 3 moves **41 A-marks**, so it is examiner judgment.

1. Strict M-then-A for the silent case — honest, but then drop the pretence
   that it is principle-driven.
2. No unconditional default; require justification from the principles plus
   the scheme's own `dep`/`ft`/`ecf` annotations.
3. **Drive from `math_mark_type`** — the paper's own printed *mark codes*,
   where dependency actually is (57 `M` / 41 `A` / 39 `B` over 161 answer
   points, 7 of 11 fixtures). **My recommendation**, but it substitutes a
   different source than your ruling named.

**Do not close #41** — its sweep pre-authorisation is scoped to the issue's
open lifetime. The branch is held unmerged deliberately: the `VERSION` bump
invalidates the cached corpus only on merge, so landing a no-op now would
spend it and need a second bump after the real fix.

## B2 — #93: the gate-9 sweep waiver

Branch pushed, no PR, conditions 1 and 3 satisfied, sweep **null by
construction twice over** (the harness never invokes the det parser; the
golden set has zero 0625 paper-2 cases). The ask is the same
instrument-blindness waiver #38 got under A6(a).

**This is the longest chain in the queue.** #88 items 1–2 and 4, the #57
costed preflight, and the parsed-corpus regeneration are all sequenced behind
it by your own instruction.

## B3 — #37 bullet 3: the CI target cannot be re-derived

The sweep ran, aborted on its own brake, and established that
`id_positional_fallback` fired **zero** times across 39 leaves with
`id_match_rate` 1.0 in **both** arms. A corpus that scores 1.0 either way
cannot re-derive a CI target — deriving 0.99 from it would be **picking** a
number, not measuring one.

1. Leave 0.99 untouched with a recorded limitation (my lean).
2. Open a follow-up for a corpus that can actually exercise id drift.

## B4 — #95: authorised, but not executable as written

Measured this run at **$0.00**, against a throwaway directory — **nothing was
overwritten**. Evidence: `BUILD/accuracy-runs/golden-reparse-95-2026-08-26/`.

- **4 of the 5 source mark schemes do not det-parse** (all fail
  `mark_total_mismatch_escalating`). Regenerating would **destroy 10 of 11
  fixtures — the whole theory corpus** — leaving one MCQ paper.
- **Every fixture is a declared excerpt** (`case.json` holds exactly
  `is_excerpt`, and `answers.json` matches 1:1). The one paper that parsed is
  an **8-question excerpt of a 40-question paper**; regeneration would leave
  the scheme describing 40 questions while the answers and scan describe 8.

1. Abandon the rebuild — #38's waiver and #39's deferred sweep then stand
   permanently on instrument-blindness, which is the honest cost.
2. **Fix the det parser's mark-total escalation first**, as its own issue,
   with #95 held open behind it. **Still my recommendation**, but see the
   corrected estimate below — it is a work-stream, not a preliminary.
3. Rebuild MCQ-only — I advise against it.

**Corrected estimate for route 2 (run 34).** #45's failure-reason census had
already classified all 229 det failures, and all four blocked papers are in
it — looking them up cost nothing and nothing was re-derived:

| paper | cause | detail |
|---|---|---|
| `0580_s23_ms_22` | `marks_cell_notation_not_parsed` | +3, **fully explained** by 3 defaulted empty cells |
| `0606_s23_ms_12` | `mark_aggregation_overcount` | +36 |
| `0625_s20_ms_31` | `genuine_mark_total_mismatch` | −4, 34 empty cells defaulted |
| `0625_w21_ms_32` | `genuine_mark_total_mismatch` | −7, 23 empty cells defaulted |

So route 2 is **three different bugs, not one**, and only one of the four has
a mechanically closed explanation. Being careful about the label: for the two
0625 papers `genuine_mark_total_mismatch` is the census's **residual bucket**
("ruling out an overcount, column detection and cell-notation parsing"), not
a positive finding that the paper is inconsistent — #45 records that the
theory path has no shortfall heuristic, so large theory deficits fall through
to it. Their cause is **unresolved, not diagnosed**. The named unconfirmed
mechanism to look at first is empty-cell defaulting interacting with
`rows.py`'s `flush()`, which only sums a leaf's `AnswerPoints` when that
leaf's `q_row_had_answer` was set.

**Relevant to B2's priority:** the same census puts
`paper_profile_misconfiguration` at **40** — that is #93. Landing #93 alone
converts **17.5% of the entire det failure set** from failing to parsing, and
moves those 40 schemes from #88's paid-Gemini set to the free det set.

**Run 35 sharpened this further, and killed my own lead.** I tested the
`rows.py` `flush()`/`q_row_had_answer` mechanism I named above and it is
**falsified**: both deficit papers have **zero** leaves where `q.marks`
disagrees with their answer points, so no marks are lost in propagation.
Their ids are clean and their tariffs plausible, so the missing 4 and 7 marks
are **content never captured** — a table-selection question, not a marks bug.
The same inspection turned up a defect nobody had named: **duplicate
top-level question ids** (`0606` emits `9` twice; `0580`'s sequence restarts
at `1,2,8`), which breaks `(paper_id, question_id)` leaf identity independently
of mark totals. Opened as **#110**, not executed. Evidence:
`BUILD/accuracy-runs/det-mismatch-diagnosis-2026-08-26/`.

*Correcting myself: run 32's state note gave the #93 ordering as the reason to
hold #95. That was overstated — exactly one fixture is affected and #93's own
sweep found the change causally inert. It is a footnote next to the two
blockers above.*

## B5 — 17:36 item 6: where do the whitespace fixtures live?

Zero spend, but not zero risk: adding golden cases changes the corpus every
published figure is computed over (MISSION §12.2/§12.5), and #49 is reopened
so the split is **not** frozen.

1. Ordinary golden cases, accepting that they join the accuracy denominator.
2. **A metamorphic-only fixture set that `load_golden_cases` does not serve.**
   My recommendation; I will implement on your word.

## B6 — #58: the q11b settling experiment (~$0.01)

The authorised control arm came back **0/62**, so "it is just gemini churn" is
dead — but 1/31 against 0/62 is Fisher **p = 1.000**, underpowered in *both*
directions. The experiment that would settle it is re-marking q11b **alone**,
perturbed and unperturbed, ~10× each. That is a **different design** from the
one you authorised, so it is proposed and not run. Bullet 4 stays unticked
either way until it resolves.

## B7 — the 0625 paper-3 constant

`profiles.py` maps 0625 paper 3 to `THEORY_EXTENDED`; CAIE 0625 Paper 3 is
Theory (**Core**), and #93's sweep found 40 schemes flip. It is **causally
inert** today (`scheme_format` `point_based` both sides, metadata label only),
so it was left wrong-but-annotated rather than silently fixed. Own issue, or
fold into #93?

## B8 — the parsed corpus: commit when?

Your 2026-08-25 directive authorised committing the 250 parsed schemes. They
**do not exist** — that run wrote to a throwaway root. Regeneration is free
(~40 min, det-only). My recommendation stands: **regenerate and commit
immediately after #93 lands**, recording the parser SHA, because a corpus
generated today would permanently enshrine schemes that the very next merge
fixes. Say the word if you want it at 250 now anyway.

## B9 — #98: the #51 stratification axis

Two of your own records disagree. DA2 / the 2026-08-19T01:05 item says the
sample is drawn **per full 3-axis DA1 stratum** (syllabus × parse path ×
tariff band); the 2026-08-25T14:41:54 item says **mark band only**. I
implemented mark-band-only (the later, more specific record) with the axis as
a one-line parameter. It is a **pre-committed rule** — cheap now, expensive
after it ships.

## B10 — #98: ratify the deviation from DA2's hash formula

DA2 writes the rank as `sha256(relabel_salt || question_id)`. That assumes
`question_id` identifies a leaf; it does not — leaf identity is
`(paper_id, question_id)` (DA6), and `1a` recurs in every paper, so under the
literal formula every paper's `1a` shares one rank and enters the sample **as
a block**. I hash the full leaf identity instead. Nothing has been sampled
under either formula, so no committed membership changes — but it is your
decision that I altered, and I want it ratified rather than assumed.

## B11 — #98: the cleartext-salt claim (informational)

The module claimed the committed salt makes membership "unpredictable in
advance". It does not — it is cleartext. I corrected it to what the salt
actually buys: the ranking is fixed **in public before any leaf exists**, so
no analyst can mint a salt at analysis time that selects a flattering sample.
Flagging only because a false claim inside a pre-commitment matters more than
a wrong one. No action needed unless you disagree.

## B12 — #105: which measure is the headline H7 figure?

`mark_point_verdicts` is declared and never read. Agreement is currently
equality of `awarded_marks` totals, while **spec §6 defines pass-2 output per
mark point**. These are different measurements — two labellers can award 2/3
by matching *different* mark points and count as agreeing. Which is the
published H7 number?

## B13 — #59: authorise the `GoldenCase` two-render data-model change?

Decisions 1 and 2 landed. The measurement itself is blocked: `GoldenCase`
holds exactly one scan slot (`harness.py:66`, `:115` hard-codes `"scan.pdf"`),
so "same paper, two renders" is not expressible. That is a data-model change
and #59's stated "Effort: S" is wrong. Authorise it as its own work, or park
#59?

## B14 — still owed on the H issues

Not decisions I can make or work around (MISSION §3.5):

- **#51** — labeller B's identity and onboarding.
- **#52** — the three seed rulings themselves (ECF, `oe` alternatives, list
  rule over-tariff). The machinery is built and the log ships empty; the
  rulings are examiner judgment and I will not draft them.
- **#49** — split membership stays **NOT frozen** until #57 delivers and you
  sign off.
