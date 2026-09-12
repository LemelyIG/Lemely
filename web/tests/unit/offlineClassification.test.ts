import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { isOfflineFailure } from "@/lib/offlineFailure"

/*
 * A4 · Which query failures are "offline" rather than "broken".
 *
 * `QueryState`'s error branch renders `OfflineState` for these, `ErrorState`
 * for everything else — see that module for why the distinction matters (a
 * dropped connection is not the same fact as a 500, and telling them apart is
 * the whole point of `OfflineState` existing as a third `StateView` kind
 * alongside `error`/`empty`). `request()` in `lib/api.ts` synthesises
 * `ApiError(0, ...)` for every `fetch` rejection before it reaches a query's
 * `error` field — that is the ONLY shape this client's own network failures
 * take by the time `QueryState` sees them, which is why a bare `TypeError` is
 * deliberately NOT treated as offline here: nothing in this client's request
 * path lets one reach `query.error` for a dropped connection, so classifying
 * it as offline would just as readily mislabel a genuine application bug
 * (review's finding — a `TypeError` from `undefined.map`, say) as "you're
 * offline".
 */

describe("isOfflineFailure", () => {
  it("classifies a status-0 ApiError as offline", () => {
    expect(isOfflineFailure(new ApiError(0, "Failed to fetch"))).toBe(true)
  })

  it("does not classify a bare TypeError as offline", () => {
    // A TypeError reaching `query.error` in this client is an application
    // bug (e.g. `.map` on `undefined`), never a dropped connection — see the
    // module header. Labelling it "offline" would hide that bug behind the
    // wrong, reassuring message.
    expect(isOfflineFailure(new TypeError("Cannot read properties of undefined"))).toBe(false)
  })

  it("does not classify a real HTTP error status as offline", () => {
    expect(isOfflineFailure(new ApiError(500, "Internal Server Error"))).toBe(false)
    expect(isOfflineFailure(new ApiError(404, "Not Found"))).toBe(false)
  })

  it("does not classify a non-network error as offline", () => {
    expect(isOfflineFailure(new Error("something else"))).toBe(false)
    expect(isOfflineFailure(undefined)).toBe(false)
  })
})

/*
 * A4 review (MEDIUM 3) · `isOfflineFailure` being correct in isolation
 * doesn't prove `QueryState`'s error branch actually calls it. This repo has
 * no jsdom/@testing-library (`vitest.config.ts`'s own header — component
 * behaviour is covered by Playwright E2E instead), so a real render of
 * `<QueryState status="error">` asserting `role="status"` isn't available
 * here; this is the source-level check `queryStateGate.test.ts` and
 * `failureCopy.test.ts` already use for the same reason. It fails if the
 * error branch stops consulting `isOfflineFailure`, or stops choosing
 * between `OfflineState`/`ErrorState` with it.
 */
describe("QueryState's error branch wiring (source-level check)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "query-state.tsx"),
    "utf8",
  )

  it("imports isOfflineFailure from the module this test exercises", () => {
    expect(source).toMatch(
      /import\s*\{\s*isOfflineFailure\s*\}\s*from\s*["']@\/lib\/offlineFailure["']/,
    )
  })

  it("imports OfflineState alongside ErrorState", () => {
    expect(source).toMatch(/import\s*\{[^}]*\bErrorState\b[^}]*\bOfflineState\b[^}]*\}/s)
  })

  it("chooses OfflineState vs ErrorState by calling isOfflineFailure on query.error", () => {
    expect(source).toMatch(
      /isOfflineFailure\(query\.error\)\s*\?\s*OfflineState\s*:\s*ErrorState/,
    )
  })
})
