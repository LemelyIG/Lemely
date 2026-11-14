import { describe, expect, it } from "vitest"
import { isSameUrl } from "@/lib/nav/dialogExit"

const at = (pathname: string, search = "", hash = "") => ({ pathname, search, hash })

describe("isSameUrl (polish B, item 18)", () => {
  it("is the same URL for an absolute path equal to the current one", () => {
    expect(isSameUrl("/student/notifications", "/student/notifications", at("/student/notifications"))).toBe(true)
  })

  it("is not the same URL when the search differs", () => {
    expect(isSameUrl("/a?x=1", "/a", at("/a", "?x=2"))).toBe(false)
    expect(isSameUrl({ pathname: "/a", search: "?" }, "/a", at("/a"))).toBe(true)
  })

  it("respects the hash: the same page at another anchor is a destination", () => {
    expect(isSameUrl("/a#top", "/a", at("/a", "", "#bottom"))).toBe(false)
    expect(isSameUrl("/a#top", "/a", at("/a", "", "#top"))).toBe(true)
    expect(isSameUrl("/a", "/a", at("/a", "", "#top"))).toBe(false)
    expect(isSameUrl({ pathname: "/a", hash: "#" }, "/a", at("/a"))).toBe(true)
  })

  it("resolves a relative target against the base it is given (the route, not the address bar)", () => {
    expect(isSameUrl("settings", "/student", at("/student/settings"))).toBe(true)
    // Against the address bar's deeper path, the same relative `to` lands somewhere else.
    expect(isSameUrl("settings", "/student/settings", at("/student/settings"))).toBe(false)
    expect(isSameUrl(".", "/student", at("/student"))).toBe(true)
  })
})
