import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Source-text gates for the history branch of `PaperResult` (spec
 * 2026-09-17 student self-review, Part 4). Neither the screen nor the hook is
 * mountable under this suite's DOM-less Node environment
 * (`vitest.config.ts`, D3.20), so the wiring is pinned as text — the same
 * reasoning `capabilityWiring.test.ts` and `routeErrorWiring.test.ts` record.
 *
 * What these gates exist to catch: the history branch rendered a permanent
 * `questions={[]}` for as long as history results carried no per-question
 * rows. That literal is now wrong, and reintroducing it — or dropping the
 * `enabled` gate so a file-store record fires a request at
 * `/student/attempts//questions` — breaks the surface silently, because a
 * screen with no rows looks exactly like a paper that has none.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("useSelfReviewApi.ts — useAttemptQuestions", () => {
  const source = readSource("src/lib/hooks/useSelfReviewApi.ts")

  it("calls the attempt-questions endpoint by attempt id", () => {
    expect(source).toContain("/student/attempts/${encodeURIComponent(attemptId ?? \"\")}/questions")
  })

  it("stays disabled without an attempt id, so a file-store record fires no request", () => {
    expect(source).toContain("enabled: !!attemptId")
  })

  it("requests no fallback value, so a rejected request() reaches useQuery as isError", () => {
    expect(source).not.toContain("fallback")
  })
})

describe("PaperResult.tsx — the history branch renders real rows", () => {
  const source = readSource("src/portals/student/screens/PaperResult.tsx")

  it("renders HistoryQuestions rather than a hardcoded empty list", () => {
    expect(source).toContain("<HistoryQuestions")
    expect(source).not.toContain("questions={[]}")
  })

  it("feeds the hook the result's own attempt id", () => {
    expect(source).toContain("useAttemptQuestions(result.attemptId)")
  })

  it("renders the rows the query returned, never data.theory", () => {
    expect(source).toContain("questions={rows}")
    expect(source).not.toContain("questions={data.theory}")
  })

  it("renders an error state on a non-404 failure, distinct from the honest-empty list", () => {
    expect(source).toContain("questions.isError")
    expect(source).toContain(
      'questions.error instanceof ApiError && questions.error.status === 404',
    )
    expect(source).toContain("<ErrorState")
  })
})

/*
 * Task 13 · source-text gates for `useSelfReview`/`useSubmitSelfReview`.
 * Neither hook has a mountable consumer yet (Task 14/15 build the panel), so
 * this pins the reveal-safety contract as text, same reasoning as the block
 * above and `capabilityWiring.test.ts`/`routeErrorWiring.test.ts`.
 */
describe("useSelfReviewApi.ts — useSelfReview / useSubmitSelfReview", () => {
  const source = readSource("src/lib/hooks/useSelfReviewApi.ts")

  it("caches the POST's revealed payload under the SAME key the pending GET reads", () => {
    // Both calls must build the key through the one selfReviewKey() factory —
    // a literal or a second key would let the revealed payload sit in a slot
    // the pending query, and therefore the panel, never reads.
    expect(source).toContain("queryKey: selfReviewKey(attemptId, questionResultId)")
    expect(source).toContain("setQueryData(selfReviewKey(attemptId, questionResultId), data)")
  })

  it("writes the cache only from onSuccess, never before the POST resolves", () => {
    // The absence of `onMutate` is not, by itself, the reveal guarantee: a
    // `setQueryData` call slipped into `mutationFn` (before `request()`
    // resolves) fabricates the same client-invented verdict `onMutate` would,
    // under a different name. `onMutate` was checked for; a comma-expression
    // write hidden in `mutationFn`'s body proved that a lone keyword-absence
    // assertion is not (Task 13/14 review, SF-1, evasion E5). So this pins
    // both: no `onMutate` anywhere, exactly one `setQueryData(` call in the
    // whole file, and that one call lives inside `onSuccess:`, after `data`
    // (the server's own response) is what gets written — never before.
    expect(source).not.toContain("onMutate")
    const writes = source.match(/setQueryData\(/g) ?? []
    expect(writes).toHaveLength(1)
    const onSuccessStart = source.indexOf("onSuccess:")
    expect(onSuccessStart).toBeGreaterThan(-1)
    const onSuccessBody = source.slice(onSuccessStart)
    expect(onSuccessBody).toContain(
      "setQueryData(selfReviewKey(attemptId, questionResultId), data)",
    )
    // And the mutation's own function body — everything before `onSuccess:`
    // — must not itself contain a write, which is the placement E5 exploited.
    expect(source.slice(0, onSuccessStart)).not.toContain("setQueryData(")
  })

  it("does not retry a 404 (or any other final 4xx) on the GET", () => {
    expect(source).toContain(
      "!(error instanceof ApiError && error.status < 500 && error.status !== 429) &&",
    )
  })

  it("re-syncs the self-review query on a 409 or a network failure (Task 13/14 review, IMP-1)", () => {
    // A 409 means the server already holds a pass; a non-ApiError failure
    // means the client cannot tell whether the POST landed. Either way the
    // cached `not_started` view may now be a lie, and the only fix that does
    // not leave the student staring at a form for a pass already recorded is
    // to invalidate the exact slot the pending GET reads.
    const onErrorStart = source.indexOf("onError:")
    expect(onErrorStart).toBeGreaterThan(-1)
    const onErrorBody = source.slice(onErrorStart)
    expect(onErrorBody).toMatch(
      /invalidateQueries\(\{\s*queryKey: selfReviewKey\(attemptId, questionResultId\),\s*\}\)/,
    )
    expect(onErrorBody).toMatch(/!\(error instanceof ApiError\)\s*\|\|\s*error\.status === 409/)
  })

  it("invalidates every total-bearing student surface on submit", () => {
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "overview"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "subject"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "result"] })')
  })
})
