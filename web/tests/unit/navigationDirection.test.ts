import { describe, expect, it } from "vitest"
import { navigationDirection } from "@/lib/nav/navigationDirection"

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
})
