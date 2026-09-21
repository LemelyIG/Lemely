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
