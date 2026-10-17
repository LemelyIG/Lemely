import { describe, expect, it } from "vitest"
import { backTarget } from "@/lib/nav/backTarget"

/*
 * Packet B2a · `BackControl` (student sub-screens) and, later, Task 4's
 * edge-swipe-back both resolve their destination through this: real browser
 * history when this tab has some (a deep link followed within the app),
 * otherwise the portal's own fallback route (a fresh tab / deep link landed
 * directly on the screen, where `navigate(-1)` would leave the app or land
 * outside it).
 */

describe("backTarget", () => {
  it("prefers real history when the entry index is greater than zero", () => {
    expect(backTarget(3, "/student")).toEqual({ kind: "history" })
    expect(backTarget(1, "/student")).toEqual({ kind: "history" })
  })

  it("falls back to the route when the entry index is exactly zero — this is the first entry in the tab", () => {
    expect(backTarget(0, "/student")).toEqual({ kind: "route", to: "/student" })
  })

  it("falls back to the route when the index is undefined", () => {
    expect(backTarget(undefined, "/student")).toEqual({ kind: "route", to: "/student" })
  })

  it("falls back to the route when the index is null", () => {
    expect(backTarget(null, "/student")).toEqual({ kind: "route", to: "/student" })
  })
})
