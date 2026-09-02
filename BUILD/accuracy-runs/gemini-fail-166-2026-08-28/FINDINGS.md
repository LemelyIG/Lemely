# #166 — the Gemini mark-scheme parse failure, DIAGNOSED (ruling C22)

**Spent $0.376981 of the $0.50 cap. 3 attempts on one scheme, 6 Gemini calls.
Stopped inside the cap; no fourth run made.**

Target `0606_m21_ms_22` — still a det failure after #136, still 0606, and the
scheme the C20 probe had seen fail then succeed unchanged.

## The answer: every call reached the API and returned 200. Nothing is failing
## in Gemini. **The response fails `MarkScheme` Pydantic validation, twice, and
## the client gives up.**

`GeminiClient` validates, and on failure re-prompts once with the schema (a
"schema-correction retry"). Both attempts failing is what produces
`status="failed"` with the message *"Gemini response did not validate against
MarkScheme even after schema-correction retry."*

## Intermittent AND systematic — and that is not a contradiction

**3 of 3 attempts failed** (plus the C20 probe's 1 of 2), so the outcome is
systematic. But **no two failures were the same failure**:

| attempt | call | validation error |
|---|---|---|
| 2 | first | **72 errors** — `questions.2.parts.0.id/marks/type Field required, input_value={}` |
| 2 | retry | **69 errors** — same shape, empty `{}` objects in `parts` |
| 3 | first | **1 error** — `Question '11a_ii': sum of primary mark points (3) exceeds total marks (2)` |
| 3 | retry | **1 error** — `Question '12_cont': sum of primary mark points (3) exceeds total marks (2)` |

Different mechanism, different question, every time. **So the question "is it
intermittent or systematic" was the wrong dichotomy.** The per-*call* failure is
stochastic; the per-*paper* outcome is near-certain, because a paper fails if
**any** of its questions fails. That single fact explains both open patterns:

- **Why bigger schemes fail more (10.0 pages vs 7.3).** More questions is more
  independent chances to trip a validator. `P(paper ok) = (1 − p)^n_questions`
  falls off fast even for small per-question `p`. It is not that long documents
  confuse the model; it is that a paper-level all-or-nothing gate compounds.
- **Why 0606 fails at 0%.** Additional Mathematics prints **alternative solution
  routes** more than any other syllabus in the corpus. Gemini emits them as
  separate *primary* answer points, so their sum exceeds the tariff and
  `Question.validate_mark_point_sum` (`loose_schemas.py:910`) raises. That
  validator already excludes `is_alternative` and `is_optional` points —
  **the model is simply not setting the flag.**

**This is the same defect as #112 and #136 mechanism (D), on the other path.**
Both parsers mis-handle CAIE's alternative routes: det summed bracketed `(A1)`
cells (fixed in #136) and misses textual `OR`/`Alternative` markers (#112, open);
Gemini emits alternative points without `is_alternative`. Three symptoms, one
underlying thing — CAIE expresses "this is another way to earn the same marks"
in several notations and neither parser reads all of them.

## Two failure classes, not one — and only one is about alternatives

1. **Business-rule (attempt 3):** the mark-point-sum violation above. Plausibly
   fixable by prompt/schema work, at zero risk to the totals.
2. **Structural (attempt 2):** empty `{}` objects inside `parts`. That is the
   model emitting malformed output, not a semantic disagreement, and it is
   **not** explained by alternatives. Any fix must address both or it will move
   the failure rate without closing the gap.

## Why nobody had seen this in two days of runs

**The reason was never missing. It was never printed.**

- `lemely/io/mark_schemes.py:108-116` records the exception in
  `BatchParseItem.message`.
- The CLI's summary renderer prints counts and **drops `message`**.
- The full validation error, *with the raw response*, is already logged as
  `gemini_validation_failure` — **at DEBUG level**. The C20 sweep ran without
  `--verbose` and captured stdout/stderr into a variable it discarded.

So the first $0.145268 of this diagnosis bought nothing but a repeat of that,
and the remaining $0.231713 bought the answer only because this run called
`process_mark_scheme_batch` directly and kept the message. **A diagnostic that
costs money should read the fields the code already fills before it re-runs the
call.**

## What is NOT established

- **Prevalence is n=1 scheme.** Whether the ~50% corpus-wide failure decomposes
  the same way is untested; this settles the mechanism on 0606, not the mix.
- **The 2-of-4 split between classes is n=2 attempts each.** Do not size a fix
  against it.
- **No fix is proposed as costed.** Validating one would need spend, and C22
  authorised diagnosis only. A further authorisation is a fresh ask.

**Ledger: 5.993470 → 6.370451 programme-wide. Headroom $1.629549.**
