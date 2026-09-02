# #39 bullet 1 — the filtered-sum invariant, re-measured after #136's mechanism (D)

**Zero spend, det-only.** Not #39's work: an input to it, because #136 changed
the very field bullet 1's invariant filters on.

#136 mechanism (D) now sets `is_alternative=True` on **parenthesised** mark
cells (`(A1)`, `(M1)`, `(3)`), which is CAIE's notation for an alternative
route. Bullet 1 requires the invariant to be written as
`sum(p.marks for p in q.answer_points if not p.is_alternative and not p.is_optional)`
— the same filter. So both of bullet 1's figures had to be re-checked rather
than inherited.

Both arms run over the **same first 120 source schemes** (all `0580`), same
harness; the "before" arm imports a package copy with `rows.py`/`marks.py` from
`origin/develop`.

| | before | after |
|---|---|---|
| questions carrying answer points | 5,142 | 5,098 |
| answer points | 5,636 | 5,574 |
| **points flagged `is_alternative`** | **0** | **6** |
| raw-sum mismatches | 14 (2 schemes) | **15 (3 schemes)** |
| **filtered-sum mismatches** | **14 (2 schemes)** | **14 (2 schemes)** |

## Two things this says, and one it does not

**1. Bullet 1's argument is confirmed, and now has a live example on 0580.**
The raw and filtered sums used to be identical on this population (0 alternative
points, so both read 14). They now differ — raw 15, filtered 14 — because six
genuine alternative points exist. A gate on the **raw** sum would newly fail a
question that is correctly formed. That is precisely the false positive bullet 1
exists to prevent, and it is no longer hypothetical here.

**2. The filtered count did NOT move.** #136 left bullet 1's invariant exactly
as sound as it was; it did not buy the fix a passing gate.

**3. What this does NOT say.** #39 records *"filtered — 0 of 575 mismatches"*.
That is **14 of ~5,100 here, both before and after**, so the difference is
**population, not regression** — 575 is a narrower set than 120 whole `0580`
schemes. **The tautology claim in bullet 3 is population-dependent and should be
re-derived on whatever population the gate will actually run over**, not carried
across. Nothing here contradicts the original measurement on its own population.

Reproduce: `filtered_sum_probe.py <n_schemes> <package_root>`.
