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
 * `ApiError(0, ...)` for a `fetch` rejection, and a bare `TypeError` is what a
 * `fetch` call throws directly when the network is unreachable before this
 * client wraps it — both are checked here since either can reach a query's
 * `error` field depending on where in the call chain the rejection happened.
 */

describe("isOfflineFailure", () => {
  it("classifies a status-0 ApiError as offline", () => {
    expect(isOfflineFailure(new ApiError(0, "Failed to fetch"))).toBe(true)
  })

  it("classifies a bare TypeError as offline", () => {
    expect(isOfflineFailure(new TypeError("Failed to fetch"))).toBe(true)
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
