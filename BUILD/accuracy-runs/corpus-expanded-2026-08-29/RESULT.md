# The corpus went 2019–2025 → 2010–2025, and it bounded the det path

**Zero Gemini spend.** PaperScraper downloaded 1,332 documents, 0 failed;
canonical mark schemes **479 → 1,130**, question papers **479 → 1,134**. Only 5
question papers lack a matching scheme. Then a det-only re-parse of all 1,130.

## Why the headline coverage figure fell

| | schemes | exact | rate |
|---|---|---|---|
| **2019–2025** | 477 | 331 | **69.4%** |
| **2010–2018** | 299 | 62 | **20.7%** |
| **all** | 1,130 | **393** | **34.8%** |

The 2019–2025 row **reproduces the 331 measured earlier**, which is what makes
the two populations comparable rather than merely different.

**Nothing got worse. The measurement got honest.** Every parser fix this session
was built and validated on 2019–2025 papers; that population had **2** parse
errors, and the expanded one has **354**. `331 of 479` was measured on the easy
decade.

## The one defect worth fixing, and it is fixed

Of 438 initial failures, **411 (93.8%)** were a single cause, and **every
affected session was 2010–2016**:

```
2017+     "Maximum Mark: 70"
2010–16   "0580/21 Paper 2 (Extended), maximum raw mark 70"
```

`_MAX_MARK_RE` only knew the newer wording, so the parser **raised before looking
at a single question**. Sampled 45 errored schemes before touching it: **41 said
`maximum raw mark`**; the other 4 used modern wording and failed for the causes
already counted.

`raw` is optional but **specific** — a permissive gap would let cover prose
("the maximum number of candidates per mark is 99") supply the number, and a test
pins that such a cover still raises.

**Effect: errors 438 → 354, parsed 692 → 776.**

## And it bought ZERO additional coverage

**`exact` stayed at 393.** All 84 newly-parsing schemes landed in `not_exact`.
In production, where `escalate_on_mark_mismatch` is on, a scheme that parses but
does not reconcile raises anyway — so **the fix changes the diagnostic picture,
not the routing.** It is correct and necessary, and on its own it is not an
improvement to det coverage.

The 2010–2018 exact **rate** even fell, 28.8% → 20.7%, because the denominator
grew while the numerator did not. Same shape as DA39: a fix can make a rate look
worse.

## A hypothesis of mine, falsified in one check

The remaining errors are dominated by *"No tables found — may be a scanned PDF"*,
and I was about to report that older CAIE schemes are image scans and structurally
out of reach.

**They are not.** Measured on the same page index:

| | mean text chars/page | mean tables/page |
|---|---|---|
| errored 2010–16 | **872** | **1.30** |
| parsed 2019–25 | 1,029 | 0.95 |

The errored papers have **more** extractable text and **more** tables than the
ones that parse. **The error message is the parser's guess, and the guess is
wrong.**

## What actually blocks them

The pre-2017 layout has no ruled row separators, so pdfplumber returns **a whole
page of questions as one 2-row table**, with question boundaries as newlines
*inside* cells:

```
header=['1 a =3, b=2, c=1',  'B1, B1,\nB1\n[3]',        'B1 for each']
header=['3\n1+sinθ cosθ (1', 'M1\nDM1\nDM1\nA1\n[4',    'M1 for dealing w']
```

`qualifies_as_mark_scheme_table` rejects these **correctly** — they are not
row-per-question tables. Supporting them means splitting cells on newlines and
re-aligning columns: **a second parsing strategy, not a tweak**, and properly its
own issue.

## What this says for the programme

- **The det path's reach is bounded by CAIE's layout change at 2016/17**, not by
  parser quality. Expanding the corpus backwards does not expand det coverage.
- For 2010–2016 the **Gemini path is the only option** — and #166 measured it
  failing on ~50% of what det cannot parse.
- **Every corpus-wide figure published before today is as-of the 479-scheme
  population** and must be labelled that way, not silently reused.
