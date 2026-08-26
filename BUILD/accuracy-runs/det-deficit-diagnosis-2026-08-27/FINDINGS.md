# #136 — the two 0625 deficits: three more hypotheses falsified, loss localised

Det-only, read-only, **$0.00**. Reproduce with `probe.py`.

B4 recorded these as **UNRESOLVED, not diagnosed**, and named the `rows.py`
`flush()`/`q_row_had_answer` lead as already falsified so it would not be
re-derived. This run does not re-derive it. It rules out three *further*
places the loss is not, and narrows where it is.

| paper | max | parsed | deficit | roots | leaves |
|---|---|---|---|---|---|
| `0625_s20_ms_31` | 80 | 76 | **−4** | 12 | 41 |
| `0625_w21_ms_32` | 80 | 73 | **−7** | 12 | 43 |

## NOT the mechanism — three hypotheses killed with evidence

**1. Table selection.** This was the *stated* next place to look after run 35
("a table-selection question"). **It is wrong.** Every table dropped by
`select_tables` is a non-mark-scheme table, correctly rejected:

- `s20`: 3 dropped — `GENERIC MARKING PRINCIPLES`, the numbered principles
  table, and the `'List rule' guidance` table.
- `w21`: 7 dropped — the same two, plus calculation guidance, the
  `Examples of how to apply…` table, **two** `annotation | suggested use`
  legend tables, and a `property | object` table on p10.

No question-bearing table is discarded in either paper. Recorded so the next
attempt does not spend a run here, exactly as B4 asked of the `rows.py` lead.

**2. Mark-cell notation.** `parse_marks_cell` handles both notations these
papers actually use, and **nothing in the marks column fails to parse**
(`unparsed={}` on both). Worth stating because `w21` genuinely *mixes* them —
`B1`/`A1`/`C1`/`M1`/`B3` codes alongside bare `2` and `3` — which looks like a
promising mechanism and is not one. `B4` correctly yields 4 marks, `2` yields 2.

**3. Propagation into leaves.** Independently reproduces run 35 on a wider
check: **zero** zero-mark leaves, **zero** leaves without answer points, and
**zero** leaves whose `marks` disagrees with the sum of their own answer
points, on both papers. The parsed structure is internally consistent
end to end.

## Where that leaves the loss

Every parsed leaf is consistent, every mark cell parses, and no
question-bearing table is dropped — so the missing 4 and 7 marks are **rows
that never became answer points at all**, upstream of leaf assembly and
downstream of table selection. That is `rows.py`'s row-consumption path, but
**not** the `flush()`/`q_row_had_answer` mechanism B4 already falsified.

**Not diagnosed further, and not guessed.** #136's acceptance asks for a named
mechanism, and "somewhere in row consumption" is not one. What this run buys is
that the next attempt starts inside a much smaller box, with four dead ends
already marked — the `rows.py` lead from B4, plus the three above.

## One caveat on the deficits themselves

Both papers are 0625 Paper 3 (Core Theory), 80 marks, 12 questions, and both
parse a complete-looking 12-root tree. Nothing here establishes that the
**paper** is consistent — `genuine_mark_total_mismatch` remains #45's residual
bucket, not a positive finding, and a real printed inconsistency is still not
excluded by anything measured so far.
