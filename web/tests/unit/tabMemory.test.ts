import { describe, expect, it } from "vitest"
import { tabRoot } from "@/lib/nav/tabMemory"

/*
 * Packet B3 (Task 4) · `tabRoot` is the pure half of `useTabState` — which
 * pathnames count as "a tab", so switching Overview -> Classes -> Overview
 * shares one memory slot while a drilldown (`/student/subject/9709`) gets its
 * own, never-reused one. `useTabState` itself needs a DOM-backed
 * `useSyncExternalStore` subscriber and is exercised by the Playwright suite
 * (Task 12), same split as `scrollRestorationKey`/`ScrollRestoration`.
 */

describe("tabRoot", () => {
  it("names a tab root pathname as its own root", () => {
    expect(tabRoot("/student/classes", new Set(["/student/classes"]))).toBe("/student/classes")
  })

  it("is null for a drilldown that is not itself a tab root", () => {
    expect(tabRoot("/student/subject/9709", new Set(["/student"]))).toBeNull()
  })

  it("is null for a nested review item, not the review queue root", () => {
    expect(tabRoot("/teacher/review/abc", new Set(["/teacher/review"]))).toBeNull()
  })

  it("defaults to the real TAB_ROOTS set when none is passed", () => {
    expect(tabRoot("/student")).toBe("/student")
    expect(tabRoot("/student/subject/9709")).toBeNull()
  })
})
