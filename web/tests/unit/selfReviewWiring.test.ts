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

  it("never writes an optimistic verdict: no onMutate anywhere in the file", () => {
    // The absence IS the reveal guarantee. The server deliberately withholds
    // the verdict until the POST resolves (pending GET payload carries no
    // `awarded` at all — see selfReviewTypes.ts); an onMutate optimistic
    // write would have to invent that verdict client-side before the server
    // has actually judged anything, which is exactly the leak the spec
    // forbids. So this hook file must never define one.
    expect(source).not.toContain("onMutate")
  })

  it("does not retry a 404 on the GET — a real, final not-self-reviewable answer", () => {
    expect(source).toContain(
      "!(error instanceof ApiError && error.status === 404) && failureCount < 2",
    )
  })

  it("invalidates every total-bearing student surface on submit", () => {
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "overview"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "subject"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "result"] })')
  })
})
