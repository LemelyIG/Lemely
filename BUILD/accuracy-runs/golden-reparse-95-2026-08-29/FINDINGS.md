# #95 — blocker 1 is cleared, blocker 2 stands, and `is_excerpt` is wrong on 5 of 11 fixtures

**Zero spend, det-only, nothing regenerated.** Re-runs the 2026-08-26 feasibility
probe now that #136, #110 and #112 have landed.

## Blocker 1 — CLEARED

The 2026-08-26 probe found **4 of 5 source schemes failed to det-parse**, so
regenerating would have destroyed 10 of 11 fixtures. All five now parse to their
printed maximum exactly, and all five are duplicate-free (DA34, DA39, DA41).

## Blocker 2 — STANDS, and is now quantified per fixture

Every fixture is an **excerpt**. `answers.json` and `scan.pdf` describe only the
excerpted questions; regenerating the scheme alone replaces the excerpt with the
**full paper**, leaving ground truth that no longer corresponds to its scheme.

| fixture family | `is_excerpt` | fixture questions | fixture max | full-paper leaves | full max | blow-up |
|---|---|---|---|---|---|---|
| `0580_s23_qp_22_theory_*` (×4) | **true** | 7 | 70 | **35** | 70 | **5.0×** |
| `0606_s23_qp_12_theory_*` (×3) | **true** | 6 | 80 | **25** | 80 | **4.2×** |
| `0625_s20_qp_31_theory_*` (×3) | **false** | 7 | **19** | **41** | **80** | **5.9×** |
| `0625_m20_qp_12_mcq` | **false** | 8 | **8** | **40** | **40** | **5.0×** |
| `0625_w21_qp_32_theory_nested` | **false** | 1 | **5** | **43** | **80** | **43×** |

**Every denominator in the corpus would grow by between 4.2× and 43×**, while the
answers stay fixed to the excerpt. That is not "making scheme-parsing
measurable"; it replaces the measurement corpus with one whose ground truth does
not match it.

## New finding: `is_excerpt` is FALSE on five fixtures that are excerpts

`0625_s20_qp_31_theory_*` declares `maximum_mark: 19` against a real **80** and
carries 7 questions against **41** leaves. `0625_m20_qp_12_mcq` carries 8 of 40.
`0625_w21_qp_32_theory_nested` carries **1 question and max 5** against a
**43-leaf, 80-mark** paper.

All three families are flagged `is_excerpt: false`. **They are excerpts.**

This is adjacent to but distinct from A8's ground for retiring #39 bullet 4.
A8 retired it because `is_excerpt` is a *harness attribute, not a property of the
parsed scheme* — that ground is undisturbed. **What is new is that the flag is
also factually wrong**, so anything that did consult it would be misled about
which fixtures are partial. Nothing currently does, which is why this has been
invisible.

## Verdict

**#95 remains NOT EXECUTABLE AS WRITTEN**, for the reason the 2026-08-26 probe
gave, unchanged by three parser fixes: its scope covers regenerating the
**scheme**, and the scheme is only one of three coupled artefacts per fixture.

Regenerating `answers.json` and `scan.pdf` in step is **a far larger and more
irreversible operation than the issue describes**, and it is not what A6
authorised. That is a human decision, not an agent's to widen into.

## What is now different, and worth weighing

The 2026-08-26 probe listed **two** blockers and one is gone. The remaining one
is not about the parser at all — no amount of further parser work moves it. So
the options have narrowed to:

1. **Widen #95** to regenerate schemes, answers and scans together — the far
   larger operation, needing its own authorisation and its own effort estimate.
2. **Narrow #95** to regenerating the scheme *restricted to the excerpted
   questions*, preserving each fixture's current question set. This keeps
   denominators fixed and still routes the scheme through the parser, which is
   what makes scheme-parsing measurable. **Not free of judgment**: it requires a
   rule for "which parsed questions correspond to this excerpt", and that rule
   would be an agent inventing correspondence unless it is stated by a human.
3. **Abandon the rebuild** and accept that scheme-parsing stays unmeasurable in
   the golden harness.

**No recommendation.** Option 2 is the one that looks cheapest and is the one I
would be tempted toward, which is reason enough not to push it — it silently
introduces a correspondence rule into the measurement corpus.

## Separately actionable, and cheap

**Correcting `is_excerpt` on the five mislabelled fixtures is zero-spend, changes
no measurement** (nothing reads the flag), and stops the next reader being misled.
It is not done here because #95's scope is the rebuild, and editing fixture
metadata under a rebuild issue is how scope creep enters an irreversible corpus.
