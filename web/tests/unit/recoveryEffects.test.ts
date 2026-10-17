import { describe, expect, it } from "vitest"
import {
  RECONNECTED_PARTIAL_TOAST,
  RECONNECTED_TOAST,
  reconnectToastFor,
  shouldAnnounceReconnect, shouldRefetchOnReconnect } from "@/components/recovery-effects"

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

describe("reconnectToastFor — what the settled refetch has earned", () => {
  it("claims a full recovery only when every errored query left its error state", () => {
    expect(reconnectToastFor(3, 3)).toBe(RECONNECTED_TOAST)
  })

  it("claims a partial recovery when some are still in error", () => {
    expect(reconnectToastFor(3, 1)).toBe(RECONNECTED_PARTIAL_TOAST)
  })

  it("says nothing when every refetch failed again, or there was nothing to refetch", () => {
    expect(reconnectToastFor(3, 0)).toBeNull()
    expect(reconnectToastFor(0, 0)).toBeNull()
  })

  it("never says 'has been fetched again' unless that is true of all of them", () => {
    expect(RECONNECTED_PARTIAL_TOAST.description).not.toContain("has been fetched again")
  })
})
