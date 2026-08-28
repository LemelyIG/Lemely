# #110 + #112 — duplicate ids and alternative routes, fixed jointly

**Zero spend.** B15 required #112's three sub-defects to be fixed together and
**run jointly with #110**; ruling C1 waived the marking sweep (the golden harness
reads pre-parsed `mark_scheme.json` and never invokes the det parser, so both
arms would be identical inputs) and put a **zero-spend deterministic corpus
before/after** in its place. This is that.

Both arms re-parse all **479** source schemes; the before arm imports a package
copy with `rows.py` taken from `origin/develop`.

| | before | after |
|---|---|---|
| schemes reconciling **exactly** | 333 | **331** |
| corpus-wide parsed marks | 32,913 | **32,849** (**−64**) |
| points flagged `is_alternative` | 1,084 | **1,257** |
| **leaves lost to id collapse** | **57** | **36** |
| **schemes with duplicate leaf ids** | **34** | **21** |

## #110 — duplicate ids

**Prevalence, measured (bullet 1):** **34 of 477 parsed schemes (7.13%)**, **57
leaves collapsing** out of 17,064. The finding that matters: **14 of the 333
schemes that reconcile with their printed maximum exactly still carry
duplicates**, so `mark_total_mismatch_escalating` is blind to this — exactly as
the issue argued.

**Mechanism (bullet 2) — there are two, and only one is unambiguous.**

1. **A question number reprinted at a page break.** CAIE repeats the number at
   the top of each continuation page and the parser opened a fresh question each
   time. `0606_w23_ms_13` opens question `10` across four consecutive tables.
2. **A stray non-question table whose first column holds small integers.**
   `0580_w21_ms_22` emits `2,3,5` in a table sitting *between* questions 20 and
   20(b) — the same root cause as #136 mechanism (C), where such rows were also
   minting marks.

**Behaviour chosen (bullet 3).** Mechanism 1 is fixed: a bare re-declaration of
the question **currently open** continues it instead of starting a new one.
**Mechanism 2 is deliberately NOT auto-repaired** — going back to an earlier
number is not a page break, and silently folding it into the earlier question
would be *inventing* question identity rather than reading it.

**Detector (bullet 4).** `reconcile.check` now reports duplicate leaf ids with
the ids and the collapse count. **Unarmed by default, and that is a decision, not
an omission:** arming routes the paper to the Gemini fallback, which #166
measured failing on ~50% of the schemes det cannot parse and 100% of 0606 — so
arming trades a silently-wrong paper for a probably-absent one. Same footing as
`escalate_on_defaulted_marks`.

**Result: 57 → 36 leaves lost, 34 → 21 schemes.** The residual 36 is mechanism 2,
now visible rather than silent.

## #112 — alternative-route markers

All three sub-defects are fixed by one rule: **a line consisting solely of a
marker** (`OR`, `EITHER`, `ALTERNATIVE`, `ALTERNATIVELY`). That covers
marker-followed-by-newline (1), `Alternative` missing from the vocabulary (2),
and marker-not-at-cell-start (3).

**The line-alone requirement is what makes it safe.** CAIE also writes "accept
either form" as an *inline* or — `0625_s22_ms_33` carries
`"4000 / 10 OR 4000 / 9.8"` inside ONE mark point. Treating that as a branch
marker would split a single point and drop half its text.

**Also fixed: `EITHER` opened the alternative.** The Q-row branch already treated
`EITHER` as structural, but the continuation branch switched *into* the
alternative on it, so an `EITHER … OR …` pair scored **neither** route as
primary. `EITHER` now opens the first route; `OR`/`ALTERNATIVE` open the second.

### Three readings were measured, not argued

#112 names two itself and bounds them at **77** and **246** marks.

| reading | schemes exact | marks removed |
|---|---|---|
| **sticky** — marker governs to the end of the leaf (#112's upper bound) | 313 | **245** |
| `before` half merged as text only, carrying no mark | 304 | — |
| **non-sticky** — marker governs its own point (**shipped**) | **331** | **64** |

**Sticky reproduces #112's own upper bound almost exactly (245 against 246)**,
which is good evidence the detector finds the same marker set the issue's scan
did. It also costs 26 schemes their reconciliation. Non-sticky costs 6.

**Non-sticky is shipped**, on the ground that over-removal converts an overcount
into an *undercount* — the harder error to notice — and #112's defect is
one-directional inflation, so the conservative reading is the right default.

### The cell-splitting decision (B15)

A cell holding `primary working / OR / alternative working` carries **one** mark
awarded for **either** route, so **both halves take the row's mark** and only the
alternative is excluded from the primary sum. The alternative design — merging
the `before` half as text with no mark — was implemented and measured, and
reconciled **worse** (304 against 331). It is not carried.

### A bug in this change, found by measurement and fixed

The split's `before` half initially ignored `mark_is_alternative`, so on a
**bracketed** row (#136 mechanism D) the primary half of an already-alternative
route was counted. That pushed `0606_s23_ms_12` — which #136 had just brought to
an exact 80 — up to **82**. Fixed and pinned by a test; it is back to 80/80.
**Two independent alternative-route mechanisms can fire on the same row, and
neither may re-admit what the other excluded.**

## The pre-stated prediction: MISSED, low side

#112 predicted **77–246 marks** removed. Measured: **64**. Outside the band.

The gap is the **cell split**: #112's lower bound reclassified the *whole*
marker-bearing point as alternative, whereas splitting keeps its primary half.
That is a difference in what the fix does, not a measurement error — but it is
**inferred from the design, not separately measured**, and is recorded as such.

## Why `exact` fell (333 → 331) and why that is not a rejection

**Reconciliation is a confounded criterion for this fix and must not be used to
accept or reject it.** #112's defect *inflates* totals, so a paper that
reconciled while summing both routes must also have been *under*-counting
somewhere else. Removing the double-count exposes the undercount, and the paper
stops reconciling while becoming more correct — the same "exact by cancellation"
pattern #136 recorded, now seen a third time.

The six schemes that left exact were inspected rather than assumed. All are
genuine alternatives: `0625_s25_ms_41` prints `F = ∆p/(∆)t AND …` **OR**
`F = ∆{mv}/(∆)t AND …` for the same `A2`. The parser was summing both.

## Not claimed

- **No awarded mark moves yet.** The harness reads pre-parsed `mark_scheme.json`;
  the marking effect appears only when #95 regenerates the fixtures.
- **Mechanism 2 of #110 is not repaired**, only reported.
- **The 64-vs-77 explanation is inferred**, not separately measured.
