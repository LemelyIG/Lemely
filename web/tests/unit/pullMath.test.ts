import { describe, expect, it } from "vitest"
import { pullState } from "@/lib/gestures/pullMath"

/*
 * Task 5 (B4a) · the pure decision `usePullToRefresh` reduces a vertical
 * drag to: how far along the pull is (0..1, for the indicator) and whether
 * it has travelled far enough to arm a refresh on release. Kept pure and
 * tested directly since `vitest.config.ts` runs this suite under Node with
 * no jsdom (D3.20) — same reasoning as `dragMath.test.ts`.
 */

describe("pullState", () => {
  it("is 0 and unarmed regardless of dy when not at the scroll top", () => {
    expect(pullState(80, 72, false)).toEqual({ progress: 0, armed: false })
    expect(pullState(200, 72, false)).toEqual({ progress: 0, armed: false })
  })

  it("is a fraction of the threshold, unarmed, for a partial pull", () => {
    expect(pullState(36, 72, true)).toEqual({ progress: 0.5, armed: false })
  })

  it("is armed and clamped to 1 once the pull passes the threshold", () => {
    expect(pullState(80, 72, true)).toEqual({ progress: 1, armed: true })
  })

  it("is armed at exactly the threshold", () => {
    expect(pullState(72, 72, true)).toEqual({ progress: 1, armed: true })
  })

  it("is 0 and unarmed for a negative dy (pushing up, not pulling down)", () => {
    expect(pullState(-40, 72, true)).toEqual({ progress: 0, armed: false })
  })

  it("is 0 and unarmed at exactly zero movement", () => {
    expect(pullState(0, 72, true)).toEqual({ progress: 0, armed: false })
  })
})
