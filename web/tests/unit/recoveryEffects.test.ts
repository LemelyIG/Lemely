import { describe, expect, it } from "vitest"
import { shouldAnnounceReconnect, shouldRefetchOnReconnect } from "@/components/recovery-effects"

/*
 * PR 2 part C (recovery effects), pinned.
 *
 * `RecoveryEffects` itself is a mounted component with two `useEffect`s
 * reading `useQueryClient`/`useToast`/`useOnlineStatus` — none of that is
 * reachable under this suite's DOM-less Node environment
 * (`vitest.config.ts`, D3.20). What is reachable, and what actually decides
 * whether the "Reconnected" toast + refetch fire, are the two pure functions
 * the component is built around: `shouldAnnounceReconnect` (is this a
 * reconnect at all) and `shouldRefetchOnReconnect` (SHOULD-FIX 12: is there
 * actually anything to refetch, and therefore anything honest to toast
 * about).
 */
describe("shouldAnnounceReconnect", () => {
  it("announces on the offline-to-online transition", () => {
    expect(shouldAnnounceReconnect(false, true)).toBe(true)
  })

  it("does not announce while already online", () => {
    expect(shouldAnnounceReconnect(true, true)).toBe(false)
  })

  it("does not announce on the online-to-offline transition", () => {
    expect(shouldAnnounceReconnect(true, false)).toBe(false)
  })

  it("does not announce while already offline", () => {
    expect(shouldAnnounceReconnect(false, false)).toBe(false)
  })
})

describe("shouldRefetchOnReconnect (SHOULD-FIX 12)", () => {
  it("refetches (and, once that resolves, toasts) when at least one active query errored", () => {
    expect(shouldRefetchOnReconnect(1)).toBe(true)
    expect(shouldRefetchOnReconnect(5)).toBe(true)
  })

  it("skips both the refetch and the toast when nothing active is currently errored", () => {
    expect(shouldRefetchOnReconnect(0)).toBe(false)
  })
})
