import { describe, expect, it } from "vitest"
import { navigationDirection, resolveDirection } from "@/lib/nav/navigationDirection"

describe("navigationDirection", () => {
  it("reads a POP (browser back/forward) as back", () => {
    expect(navigationDirection("POP")).toBe("back")
  })

  it("reads a PUSH (a link, a programmatic navigate) as forward", () => {
    expect(navigationDirection("PUSH")).toBe("forward")
  })

  it("reads a REPLACE as forward", () => {
    expect(navigationDirection("REPLACE")).toBe("forward")
  })

  describe("resolveDirection", () => {
    it("follows the router action with no explicit direction", () => {
      expect(resolveDirection("PUSH")).toBe("forward")
      expect(resolveDirection("POP")).toBe("back")
    })

    it("keeps a re-tap pop as back", () => {
      expect(resolveDirection("PUSH", "back")).toBe("back")
    })

    it("reads a tab-bar push as a tab switch", () => {
      expect(resolveDirection("PUSH", "tab")).toBe("tab")
    })

    it("reads a pop back to a tab-tagged entry as back", () => {
      expect(resolveDirection("POP", "tab")).toBe("back")
    })

    it("reads a pop that leaves a tab-bar entry as the tab switch it undoes", () => {
      expect(resolveDirection("POP", undefined, "tab")).toBe("tab")
    })

    it("reads a pop that leaves a drill-down pushed from a tab as back", () => {
      expect(resolveDirection("POP", "tab", undefined)).toBe("back")
      expect(resolveDirection("POP", undefined, "back")).toBe("back")
    })
  })
})
