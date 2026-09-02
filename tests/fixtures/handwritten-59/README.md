# Real-handwriting fixtures (#59, M2.5)

54 rasterised pages across three CAIE 0625 Paper 42 papers, committed under
ask **C7** (2026-08-27) — the MISSION §12.7 decision to publish real-paper
content, given for this issue and scoped to it. The 2026-08-25 parsed-mark-scheme
authorisation said in terms that it was **not** blanket permission for future
real-paper content, so C7 is the grant these rest on, not that one.

## What these are

The original CAIE question-paper PDFs with **vector stylus ink drawn on top**,
then flattened to images. Per #59's limit 6: **one person (the teacher) solved
every question themselves in different coloured pens and marked their own work.
There is no student attempt here and no second author** — the ink colours must
never be treated as separable authorship. These are unrelated to
`tests/fixtures/real-papers/`, which `scripts/accuracy_notify.sh:17` governs
separately.

## Why they are flattened, and why that is load-bearing

The sources carry **intact text layers** (~23k–25k extractable characters each).
Feeding those to extraction would let the extractor read the printed question
text **without using vision at all** — measuring nothing and overstating real
performance, and not comparable with the synthetic corpus, which is rasterised
and carries 0 text characters.

Verified on the committed bytes rather than asserted:

| file | pages | text chars |
|---|---|---|
| `0625_s25_qp_42.pdf` | 20 | **0** |
| `0625_w24_qp_42.pdf` | 16 | **0** |
| `0625_w25_qp_42.pdf` | 18 | **0** |

Render settings, input/output digests and the reproducibility argument live in
`BUILD/accuracy-runs/handwritten-59/raster-manifest.json` (#102). All three
`output_sha256` values were **re-verified against these committed files** at
commit time. Re-render with `scripts/rasterise_handwritten_fixtures.py`.

## These are NOT golden cases, deliberately

They sit in `tests/fixtures/`, not `tests/golden/`, and `load_golden_cases`
does not serve them.

Promoting them to golden cases would change **corpus membership**, which is what
every published accuracy figure is computed over — the consequence accepted for
B5's whitespace fixtures, requiring every such figure to be restated. #59's
limit 5 says these papers are new to the corpus, **#49 is reopened and the split
is NOT frozen**, and they must not be frozen around silently. C7 authorised
*publishing the pixels*; it did not decide corpus membership, and that decision
is not smuggled in here.

## What can actually be measured with them, and what cannot

Checked against the local corpus rather than assumed:

| paper | mark scheme |
|---|---|
| `0625_w24_ms_42` | **parsed, in `corpus/`** |
| `0625_s25_ms_42` | source PDF exists, **not parsed** — one of the 190 det-failures (#88) |
| `0625_w25_ms_42` | **does not exist locally at all** — not in PaperScraper |

So #59's stated n = 3 is **not achievable**: it is **n = 1** today, **n = 2** if
`0625_s25_ms_42` is parsed through the Gemini path, and **never 3** unless a
`0625_w25` mark scheme is obtained. #59 already warns that n = 3 is far below any
inferential floor and that the result must be descriptive; at n = 1–2 that
warning binds harder, not less.

Unchanged and still binding: **scan realism remains unmeasured** (these are ink
on clean PDFs — no camera perspective, shadows, lighting, sensor noise or JPEG
artefacts), and the corpus is **one-sided by construction** — every answer is
correct, so it can only ever catch the marker being too **harsh**, never too
generous. Any figure published from these must say **"handwriting"** in its own
label.
