import { describe, expect, it } from "vitest"
import { shouldAnnounceReconnect } from "@/components/recovery-effects"

/*
 * PR 2 part C (recovery effects), pinned.
 *
 * `RecoveryEffects` itself is a mounted component with two `useEffect`s
 * reading `useQueryClient`/`useToast`/`useOnlineStatus` — none of that is
 * reachable under this suite's DOM-less Node environment
 * (`vitest.config.ts`, D3.20). What is reachable, and what actually decides
 * whether the "Reconnected" toast + refetch fire, is the one pure function
 * the component is built around: `shouldAnnounceReconnect`.
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
