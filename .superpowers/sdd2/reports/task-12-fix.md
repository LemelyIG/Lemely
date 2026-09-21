# Task 12 fix report — SHOULD-FIX 1–6, NIT 1–3

Fixes findings from `.superpowers/sdd2/reports/task-12-review.md` (verdict: CHANGES REQUIRED,
0 MUST-FIX, 6 SHOULD-FIX, 3 NIT). All nine addressed. Brief corrected in the same pass per
review §5.

Files touched: `web/src/lib/selfReview.ts`, `web/tests/unit/selfReview.test.ts`,
`.superpowers/sdd2/briefs/task-12.md`. `web/src/lib/selfReviewTypes.ts` needed no code change —
the SHOULD-FIX 3 guard lives in the test file, not the type file — but its brief fence is
unaffected too.

## SHOULD-FIX 1 — `ABSORBED_COPY` false in a mixed-direction group under cap

`web/src/lib/selfReview.ts:107-117`. Took the reviewer's option 1: replaced the causal,
cap-asserting sentence with a direction-agnostic, non-causal one.

- New text: *"Accepted, but this point is grouped with others on this question, so the group's
  total did not change."* Asserts only that the claim was accepted and the group's total held —
  true in every case the review enumerated (A, B, and the mixed-direction net-zero case C).
- Did **not** attempt a causal line — that needs sibling-point context `outcomeDetail` doesn't
  receive, which the reviewer correctly scoped as a Task 14 API change, out of this task's brief.
- **Label/detail contradiction, resolved.** `OUTCOME_LABEL.kept` was "The marker's mark stands"
  while the detail said "Accepted...". Changed the label to "This point's mark did not change" —
  a claim about the *mark*, true in both the absorbed case (mark held despite a grant) and the
  plain-rejected case (mark held because nothing was granted), so it no longer contradicts
  either detail line.
- New test: `says nothing false about ABSORBED_COPY: no cap claim, no 'already have' claim` —
  asserts the string mentions "group" and excludes the exact falsehood family
  (`already earned all|already have|shares its mark`).

## SHOULD-FIX 2 — `summaryLine` asserts finality while a teacher may still move the mark

`web/src/lib/selfReview.ts:149-160`. Added a `pendingTeacher` branch before the numeric
comparison, per the reviewer's suggested shape:

```ts
if (view.pendingTeacher) {
  return `This question is at ${view.effectiveMarks} out of ${view.maxMarks} while a teacher looks at one of your reasons.`
}
```

Placed after `teacherSettled` (a teacher *has* looked — final) and before the aiMarks/effectiveMarks
diff, so it fires regardless of whether marks from other points already moved.

New test `does not assert finality on the headline while a teacher is still going to look`
checks both: the plain pending case doesn't say "stays at", and a case where marks *did* move
for another point still doesn't say "moved this question from" — the pending line takes priority.

## SHOULD-FIX 3 — nothing stopped `awarded` re-entering the pending type

Added a compile-time guard to `web/tests/unit/selfReview.test.ts:31-42`:

```ts
type HasAwarded<T> = "awarded" extends keyof T ? true : false
const _pendingHasNoVerdict: HasAwarded<SelfReviewPendingPoint> = false
const _revealedHasVerdict: HasAwarded<SelfReviewRevealedPoint> = true
```

**RED proof (mutation M8 reintroduced):** added `awarded?: boolean` to
`SelfReviewPendingPoint` in `selfReviewTypes.ts`, ran `npm run typecheck`:

```
tests/unit/selfReview.test.ts:39:7 - error TS2322: Type 'false' is not assignable to type 'true'.
const _pendingHasNoVerdict: HasAwarded<SelfReviewPendingPoint> = false
Found 1 error.
```

Reverted; `npm run typecheck` clean again. The second assertion (`_revealedHasVerdict: ... = true`)
proves the guard isn't vacuous — it would itself fail to compile if `HasAwarded` were broken in a
way that always returned `false`.

## SHOULD-FIX 4 — copy scan covered 6 of 13 emitted strings

`web/tests/unit/selfReview.test.ts` (`names the evidence rule...` test): rebuilt `allCopy` from
every string the module can emit — the two `evidenceHint` outputs, `UNAVAILABLE_COPY`,
`ABSORBED_COPY` (previously missing), all four `OUTCOME_LABEL` values, and six `outcomeDetail`
outputs covering every non-null branch (`changed`/accepted, `changed`/not_required,
`kept`/rejected, `kept`/absorbed, `kept`/evidence-required-no-verdict, `pending`) — 14 strings
total, up from 6.

## SHOULD-FIX 5 — `ABSORBED_COPY` and labels asserted only against themselves

- `ABSORBED_COPY`: added content assertions (see SHOULD-FIX 1 above) instead of relying solely
  on `toBe(ABSORBED_COPY)` identity checks (those checks stay, they prove routing).
- `OUTCOME_LABEL`: new test asserts the four values are mutually distinct
  (`new Set(values).size === values.length`) and each matches a phrase carrying its meaning
  (`/agree/i`, `/applied|mark/i`, `/did not change|stands|unchanged/i`, `/teacher/i`).
- `UNAVAILABLE_COPY`: new test asserts `/not available/i` and `/paper/i`.

## SHOULD-FIX 6 — `outcomeDetail`'s `pending` branch untested

New test `tells the student a teacher will look, for the one point still unjudged`:
`outcomeDetail(unjudged, "pending", true)` must match `/teacher/i`.

## NIT 1 — `changed` branch ignored `evidenceRequired`/asserted an ungated inference

`web/src/lib/selfReview.ts:128-133`. Gated the "not sure" line on `evidenceVerdict === "not_required"`
explicitly; anything else (defensively, e.g. `rejected`) now returns `null` rather than an
unconditional, potentially wrong inference. New test confirms the `null` fallback for a
`rejected` + `markChanged` combination (not reachable today per the backend invariant the
reviewer cited, but the gate is now real rather than assumed).

## NIT 2 — no client-side bound on evidence length

Left as-is per the review: this belongs to Task 14's textarea (`maxLength`), not this task's
scope. Flagging again here so it isn't lost.

## NIT 3 — `isComplete`'s runtime check was weakenable, untested

New test `only counts an actual boolean as a verdict, not merely a present key`: a verdict of
`"true"` (string) rather than `true` (boolean) must make `isComplete` return `false`.

**RED proof (mutation M5 reintroduced):** changed the `typeof ... === "boolean"` check to
`!== undefined`, ran the suite:

```
FAIL  ... > only counts an actual boolean as a verdict, not merely a present key
AssertionError: expected true to be false
```

Reverted.

## Mutation-kill evidence — all reviewer mutations that survived now killed

Each mutation reapplied verbatim from the review's §4 table, suite run, then reverted with the
original committed file restored via a local backup and diffed byte-identical afterward.

| # | Mutation | Before (review) | After (this fix) |
|---|---|---|---|
| M1 | `ABSORBED_COPY` → junk string | 17 passed (SURVIVED) | 2 tests failed (KILLED — copy scan + content test) |
| M2 | `pending` branch → `return null` | 17 passed (SURVIVED) | 1 test failed (KILLED — new pending test) |
| M3 | `OUTCOME_LABEL` values → junk | 17 passed (SURVIVED) | 1 test failed (KILLED — distinctness/content test) |
| M4 | `judgeReason` fallbacks → integrity-flag copy | 17 passed (SURVIVED) | 1 test failed (KILLED — copy scan) |
| M5 | `isComplete` `typeof` → `!== undefined` | 17 passed (SURVIVED) | 1 test failed (KILLED — NIT 3 test) |
| M7 | `evidenceHint`/`UNAVAILABLE_COPY` gutted | 17 passed (SURVIVED) | 1 test failed (KILLED — UNAVAILABLE_COPY content test) |
| M8 | `awarded?: boolean` added to pending type | 17 passed + typecheck clean (SURVIVED) | typecheck fails (KILLED — `HasAwarded` guard) |
| M6 | `effectiveMarks !== aiMarks` → `===` | 1 failed (already KILLED, sanity check) | not re-run — was never a gap |

All 7 surviving mutants from the review are now killed. Full transcripts for M1, M2, M3, M4, M5,
M7 were captured during this fix pass (each is a single failing-test run against the mutated
`selfReview.ts`, restored immediately after via `cp` from a pre-mutation backup, confirmed
byte-identical to the original with `diff`). M8 was captured against `selfReviewTypes.ts` via
`npm run typecheck`.

## Final verification

```
$ npx vitest run tests/unit/selfReview.test.ts
 Test Files  1 passed (1)
      Tests  24 passed (24)

$ npm run typecheck
(clean, no output)

$ npm run lint
(clean for the three files touched; only pre-existing warnings elsewhere — public/shell-init.js
unused catch params, src/components/route-error.tsx react/only-export-components;
check-native-invariants: all 20 check(s) passed.)
```

## Brief corrections (`.superpowers/sdd2/briefs/task-12.md`)

Updated the Step 1 test fence and Step 4 implementation fence to match the fixed source exactly
(diffed byte-identical, modulo trailing newline, after extraction). Specifically:

- Step 1 (tests): added the `HasAwarded` guard, the strictness test (NIT 3), the `not_required`
  gate test (NIT 1), the pending-branch test (SHOULD-FIX 6), the ABSORBED_COPY content test and
  pendingTeacher summaryLine test (SHOULD-FIX 1/2), the label-distinctness and UNAVAILABLE_COPY
  content tests (SHOULD-FIX 5), and the rebuilt `allCopy` scan (SHOULD-FIX 4).
- Step 3 (types): no change needed — the guard lives in the test file.
- Step 4 (impl): `ABSORBED_COPY`, `OUTCOME_LABEL.kept`, `outcomeDetail`'s `changed` case, and
  `summaryLine` all updated to match.
- Step 5: expected test count corrected from 14 to 24.

## What I did not change

- `web/src/lib/selfReviewTypes.ts` — no code change; the review confirmed no type drift and no
  re-admitted verdict field, and the SHOULD-FIX 3 fix is a test-file guard, not a type change.
- NIT 2 (evidence-length bound) — explicitly left for Task 14 per the review's own scoping.
