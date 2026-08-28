# #110 — phantom leaves pruned; the golden corpus is now duplicate-free

**Zero spend, det-only.** Continues #110 after PR #174. That PR fixed mechanism 1
(page-break reprints) and left mechanism 2 — stray non-question tables — reported
but unrepaired, on the ground that folding those rows into the earlier question
would be **inventing question identity rather than reading it**.

**This repairs the half of mechanism 2 that needs no such invention.**

## What was left behind

A data-table line beginning with a number is decomposed as a new **top-level**
question. #136 mechanism (C) already stopped those rows minting a mark. That left
them as **empty shells**: no marks, no answer points, and an id colliding with
the real question of the same number.

Dropping a node with no marks and no points is not deduping and not renumbering.
It removes something that contributes to no total, cannot be matched against a
candidate's answer, and cannot be marked — while corrupting DA6's
`(paper_id, question_id)` leaf identity.

## Deliberately narrow, in two ways — the second learned from a failing test

- **Top level only.** A labelled sub-part like `1(b)` is structure the paper
  printed and is kept even when empty. The wider rule pruned it, and a test
  caught that; only a bare top-level number can be the artefact this targets.
- **Both conditions required.** A question whose tariff was read off the page is
  real even if its answer text failed to parse.

## Measured over all 479 source schemes

| | before | after |
|---|---|---|
| schemes reconciling exactly | 331 | **331** |
| corpus parsed marks | 32,849 | **32,849** |
| total leaves | 17,043 | **16,985** |
| **leaves lost to id collapse** | **36** | **25** |
| **schemes with duplicate leaf ids** | **21** | **15** |

**Totals and reconciliation are byte-for-byte unchanged**, which is the check
that matters: pruning a zero-mark leaf cannot move a mark, and the measurement
confirms it rather than assuming it.

**58 phantom leaves were removed corpus-wide**, of which only 11 were involved in
an id collision. The other 47 were not corrupting identity — they were **inflating
the leaf count**, and therefore the denominator of every per-leaf rate the
programme computes.

## The golden corpus is now clean

`0580_s23_ms_22` was the one golden-corpus scheme still carrying duplicates —
ids `1` and `2`, each a real question plus one phantom.

| | before | after |
|---|---|---|
| duplicate leaf ids | **2** | **0** |
| leaves | 37 | 35 |
| parsed total | 70 / 70 | **70 / 70** |

**All five of #95's source schemes are now duplicate-free**, which removes the
concern raised on #95: regenerating no longer bakes collapsed leaves into the
fixtures.

## What remains

**15 schemes still carry 25 collapsed leaves.** Those are the genuinely ambiguous
half of mechanism 2 — rows with real content under a colliding id — and they are
**still reported, not repaired**. Deciding what those rows *are* is not something
the parser can read off the page.
