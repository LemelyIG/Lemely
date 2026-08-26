# #136 — the two 0625 deficits: DIAGNOSED, both mechanisms named at source

Det-only, read-only, **$0.00**. Reproduce with `probe.py`.

B4 recorded these as **UNRESOLVED, not diagnosed**, and named the `rows.py`
`flush()`/`q_row_had_answer` lead as already falsified so it would not be
re-derived. This run does not re-derive it. It falsifies three *further*
hypotheses, then names the two mechanisms that actually cause the loss and
closes the arithmetic on both papers exactly.

| paper | max | parsed | deficit | roots | leaves |
|---|---|---|---|---|---|
| `0625_s20_ms_31` | 80 | 76 | **−4** | 12 | 41 |
| `0625_w21_ms_32` | 80 | 73 | **−7** | 12 | 43 |

## The mechanism

Two distinct bugs in `rows.py`'s row consumption. Neither is the falsified
`flush()`/`q_row_had_answer` lead. Both are **silent** and both are
**one-directional — they can only ever lose marks, never invent them.**

**(A) A continuation row carrying marks but no answer text is discarded whole.**
`lemely/io/det/rows.py:311` — `if not answer_cell or not stack: continue`. The
guard exists to skip blank rows, but it fires *before* the marks column is
consulted, so a row with an empty answer cell and a real `B1` in the marks
column is dropped with its mark. `w21` `6(a)` is the case: the PDF gives it
four `B1` rows (three with empty answer cells, because pdfplumber puts the
whole matching table in the first cell), and the parser emits **one** point
worth **1** mark instead of 4.

**(B) When the mark code leaks into the answer text, the point defaults to 1
mark.** `lemely/io/det/rows.py:200` — `marks=marks_int if marks_int is not
None else 1`. In the 3-column table geometry these papers use on some pages,
the marks column merges into the answer cell, so the code arrives as trailing
text (`"...centre of mass is where lines cross B3"`) and `parse_marks_cell`
sees an empty marks cell. The default then applies.

The default is **right by luck for `B1`/`M1`/`A1`/`C1`** — which is exactly why
this survived: every single-mark code lands on the correct value. It is wrong
for every multi-mark code, losing `value − 1` marks each time, and nothing
warns.

## The arithmetic closes exactly on both papers

`probe.py` prints this attribution and asserts it against the real deficit:

| paper | (A) guard | (B) default-to-1 | total | actual deficit |
|---|---|---|---|---|
| `s20` | 0 | `B4`→1 (−3), `B2`→1 (−1) | **−4** | −4 **EXACT** |
| `w21` | 3 × `B1` (−3) | `B3`→1 (−2), `B3`→1 (−2) | **−7** | −7 **EXACT** |

Nothing is left over on either paper. That is the claim this run is willing to
make, and the reason it is stated as a diagnosis rather than a lead.

## Three hypotheses killed on the way

Recorded so the next attempt does not spend a run on them, exactly as B4 asked
of the `rows.py` lead.

**1. Table selection — the stated next-place-to-look after run 35, and it is
wrong.** Every table `select_tables` drops is a non-mark-scheme table: GMP
tables, the numbered principles, list-rule guidance, two `annotation |
suggested use` legends, a `property | object` table. **No question-bearing
table is discarded.** The `property | object` table on `w21` p10 looks like a
counter-example and is not one — pdfplumber extracts that content **twice**,
once nested inside the `6(a)` row of the real mark-scheme table and once
standalone; the standalone copy is the one dropped, so nothing is lost.

**2. Mark-cell notation.** Nothing in the marks column fails to parse
(`unparsed={}` on both). Worth recording because `w21` genuinely **mixes**
notations — `B1`/`A1`/`C1`/`M1`/`B3` alongside bare `2` and `3` — which looks
like a promising mechanism and is not one. `B4` correctly yields 4, `2` yields
2. The failure in (B) is not that the notation is unparseable; it is that the
cell never reaches the parser.

**3. Propagation into leaves.** Independently reproduces run 35 on a wider
check: **zero** zero-mark leaves, **zero** leaves without answer points, **zero**
leaves whose `marks` disagrees with the sum of their own answer points. The
parsed structure is internally consistent — consistently, and wrongly, low.

Also checked and clean, because it would have manufactured a fake deficit:
**no parent question carries marks of its own** (0 of 24 parents on each paper),
so summing leaves is a faithful total and the deficit is real loss, not a
summing artefact.

## What this retires, and what it does not

**It retires the `genuine_mark_total_mismatch` reading for these two papers.**
The previous draft of this file cautioned that a real printed inconsistency was
not excluded. It is now excluded *for these two*: the full deficit is
attributable to parser bugs, so both are **parser defects, not inconsistent
papers**, and `escalate_on_mark_mismatch` was right to block them — these are
true positives. That says nothing about the other members of #45's residual
bucket.

**It does not fix anything.** #136's fix half stays unstarted, pending the
sweep question posted on #112/#110; starting it here would produce another
complete-but-unmergeable branch.

**Prevalence is UNMEASURED.** Both mechanisms are named on n=2 papers. How
many of the 289 committed corpus schemes lose marks the same way is not known
and is not estimated here — sizing it means re-parsing PDFs, not reading the
committed JSON, because the committed output is the *post-loss* artefact and
cannot show what never became an answer point. That measurement is the natural
next step and is deliberately left to the fix half.

One consequence worth stating plainly for whoever picks that up: because both
mechanisms are one-directional, **every det-parsed multi-mark code that leaked
is currently worth 1**, so det mark totals are a *lower* bound wherever this
fires — an error that biases in a single direction is far easier to mistake for
a property of the papers than a noisy one.
