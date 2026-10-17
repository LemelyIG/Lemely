import { describe, expect, it } from "vitest"
import { healthFromResponse } from "@/lib/hooks/useServiceHealth"

/*
 * PR 2 part A2 · `healthFromResponse`, pinned.
 *
 * `useServiceHealth` itself is a hook — `useEffect`, `setInterval`, a real
 * `fetch` poll — and this repo's unit suite runs under Node with no jsdom and
 * no renderer (`vitest.config.ts`, D3.20), so the hook itself is not
 * reachable here. `healthFromResponse` is the one part of it that is pure: the
 * three-way mapping from "have we checked yet, and did it succeed" to the
 * status `FullPageState` renders, exported from `useServiceHealth.ts`
 * specifically so this file can pin it without mocking a timer or a fetch.
 */

describe("healthFromResponse", () => {
  it("maps null (no check has completed yet) to unknown", () => {
    expect(healthFromResponse(null)).toBe("unknown")
  })

  it("maps true to responding", () => {
    expect(healthFromResponse(true)).toBe("responding")
  })

  it("maps false to not-responding", () => {
    expect(healthFromResponse(false)).toBe("not-responding")
  })
})
