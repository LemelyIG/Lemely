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

  it("wires the panel's attemptId into the history branch's own QuestionList (final review C-2)", () => {
    // A whole-file `toContain("attemptId={")` is satisfied by the live
    // branch's own `attemptId={live.attemptId}` even when HistoryQuestions
    // passes none at all — that is exactly how this shipped: Task 18 wired
    // QuestionList's rows before Task 15 added the attemptId prop, and Task
    // 15 then wired only the live branch. Proven by mutation: deleting
    // `attemptId={result.attemptId}` from HistoryQuestions' own QuestionList
    // call leaves every other gate in this file green, and the panel never
    // renders on the persisted /student/result/:paperId route for any
    // question. Anchor on HistoryQuestions' own body instead of the whole
    // file, per the R-3 lesson.
    const fnStart = source.indexOf("function HistoryQuestions(")
    expect(fnStart).toBeGreaterThan(-1)
    const nextFn = source.indexOf("\nexport function PaperResult", fnStart)
    expect(nextFn).toBeGreaterThan(fnStart)
    const body = source.slice(fnStart, nextFn)
    expect(body).toContain("attemptId={result.attemptId}")
  })

  it("wires the panel's attemptId into the live branch's own QuestionList (final review part23, mutation M1)", () => {
    // Proven by mutation: deleting `attemptId={live.attemptId}` from the
    // live branch's own QuestionList call leaves every other gate in this
    // suite green (3353/3353), because nothing else pins this one line —
    // the panel simply never renders anywhere in the product, live or
    // history, the moment a paper is freshly marked. Anchored on the `if
    // (live) {` block's own body rather than the whole file, per the same
    // R-3 lesson the HistoryQuestions gate above already applies: a
    // whole-file `toContain("attemptId={live.attemptId}")` would pass
    // today regardless of which branch actually wires it.
    const liveStart = source.indexOf("if (live) {")
    expect(liveStart).toBeGreaterThan(-1)
    const liveEnd = source.indexOf("if (query.isError", liveStart)
    expect(liveEnd).toBeGreaterThan(liveStart)
    const body = source.slice(liveStart, liveEnd)
    expect(body).toContain("attemptId={live.attemptId}")
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

  it("the GET's own queryKey is built through the SAME key factory the POST writes to (Task 13/14 re-review, R-3)", () => {
    // A whole-file `toContain` on this exact substring can be satisfied by
    // ANY occurrence anywhere in the file — proven by the IMP-1 fix itself:
    // adding `invalidateQueries({ queryKey: selfReviewKey(attemptId,
    // questionResultId) })` inside `onError` gave the gate a second, unrelated
    // match, and mutation M2 (replacing the GET's own `queryKey:` with a
    // hand-built array) went from RED to GREEN without anyone touching the
    // GET. Anchored to the GET's own body instead: the substring must appear
    // there, and the GET's `queryKey:` line must never be a raw array.
    const queryStart = source.indexOf("export function useSelfReview(")
    const queryEnd = source.indexOf("export interface SubmitSelfReviewInput")
    expect(queryStart).toBeGreaterThan(-1)
    expect(queryEnd).toBeGreaterThan(queryStart)
    const getBody = source.slice(queryStart, queryEnd)
    expect(getBody).toContain("queryKey: selfReviewKey(attemptId, questionResultId)")
    expect(getBody).not.toMatch(/queryKey:\s*\[/)
    // The POST's cache write still goes through the same factory.
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
    // `setQueriesData` (plural: query-core's batch API, same write effect)
    // is a different call the `setQueryData(` count above does not match —
    // proven green as evasion E8 in the Task 13/14 re-review. Ban it outright
    // rather than trying to also count it: nothing in this file has a
    // legitimate reason to touch more than one query's cache at once.
    expect(source).not.toContain("setQueriesData(")
  })

  it("does not retry a 404 (or any other final 4xx) on the GET", () => {
    expect(source).toContain(
      "!(error instanceof ApiError && error.status < 500 && error.status !== 429) &&",
    )
  })

  it("re-syncs the self-review query on ANY submit failure (Task 13/14 review IMP-1, re-review R-9)", () => {
    // The first fix invalidated only on a 409 or a non-ApiError failure. The
    // re-review found a third dead end that condition missed: a gateway
    // failure (502/504/408) is an ApiError that may equally have committed
    // server-side before the gateway gave up — the same "don't know whether
    // it landed" condition a network error has. Invalidating unconditionally
    // is what a cheap, always-converges-on-the-server refetch buys: there is
    // no submit failure where re-syncing the cached view is wrong.
    const onErrorStart = source.indexOf("onError:")
    expect(onErrorStart).toBeGreaterThan(-1)
    const onErrorBody = source.slice(onErrorStart)
    expect(onErrorBody).toMatch(
      /invalidateQueries\(\{\s*queryKey: selfReviewKey\(attemptId, questionResultId\),\s*\}\)/,
    )
  })

  it("clears the draft from the option-level onSuccess, so it still runs after an unmount (Task 13/14 re-review, R-5)", () => {
    // A per-`mutate()`-call onSuccess does not fire once its caller has
    // unmounted; the option-level one passed to useMutation does. Collapsing
    // the QuestionRow right after submitting unmounts SelfReviewPanel, so
    // clearDraft has to live here, not in a callback passed from the panel.
    const onSuccessStart = source.indexOf("onSuccess:")
    const onErrorStart = source.indexOf("onError:")
    expect(onSuccessStart).toBeGreaterThan(-1)
    expect(onErrorStart).toBeGreaterThan(onSuccessStart)
    const onSuccessBody = source.slice(onSuccessStart, onErrorStart)
    expect(onSuccessBody).toContain("clearDraft(attemptId, questionResultId)")
  })

  it("invalidates every total-bearing student surface on submit", () => {
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "overview"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "subject"] })')
    expect(source).toContain('invalidateQueries({ queryKey: ["student", "result"] })')
  })

  it("also invalidates the attempt-questions rows the panel's own screen renders (final review I-1)", () => {
    // Without this, a self-mark that moves a mark leaves the row header, the
    // confidence summary and the Lost/Flagged filters showing the pre-mark
    // state on the same screen the panel just updated, until the student
    // navigates away. Anchored to onSuccess, between onSuccess: and
    // onError:, the same slice the clearDraft gate above uses.
    const onSuccessStart = source.indexOf("onSuccess:")
    const onErrorStart = source.indexOf("onError:")
    expect(onSuccessStart).toBeGreaterThan(-1)
    expect(onErrorStart).toBeGreaterThan(onSuccessStart)
    const onSuccessBody = source.slice(onSuccessStart, onErrorStart)
    expect(onSuccessBody).toContain(
      "invalidateQueries({ queryKey: attemptQuestionsKey(attemptId) })",
    )
  })
})
