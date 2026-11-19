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

  describe("a pathless target resolves against the current URL, as React Router does (final polish, item 8)", () => {
    // The caller's base is the route's pathname, deliberately different from the address bar's.
    const base = "/student"
    const here = at("/student/notifications", "?tab=all")

    it("`?x` and `#x` keep the current pathname, not the route's", () => {
      expect(isSameUrl("?tab=all", base, here)).toBe(true)
      expect(isSameUrl("?tab=unread", base, here)).toBe(false)
      expect(isSameUrl("#top", base, at("/student/notifications", "", "#top"))).toBe(true)
      expect(isSameUrl("#top", base, at("/student/notifications"))).toBe(false)
    })

    it("an object with no pathname is pathless too, and a bare search or hash is normalised", () => {
      expect(isSameUrl({ search: "?tab=all" }, base, here)).toBe(true)
      expect(isSameUrl({ search: "tab=all" }, base, here)).toBe(true)
      expect(isSameUrl({ hash: "top" }, base, at("/student/notifications", "", "#top"))).toBe(true)
      expect(isSameUrl({}, base, at("/student/notifications"))).toBe(true)
    })

    it("an empty string or empty pathname still resolves against the route", () => {
      expect(isSameUrl("", base, at("/student"))).toBe(true)
      expect(isSameUrl("", base, at("/student/notifications"))).toBe(false)
      expect(isSameUrl({ pathname: "" }, base, at("/student"))).toBe(true)
    })
  })

  describe("paths compare as the router matches them (final polish, item 8)", () => {
    it("a trailing slash is the same route", () => {
      expect(isSameUrl("/a/", "/a", at("/a"))).toBe(true)
      expect(isSameUrl("/a", "/a", at("/a/"))).toBe(true)
      expect(isSameUrl("/a//", "/a", at("/a"))).toBe(true)
      expect(isSameUrl("/", "/a", at("/"))).toBe(true)
      expect(isSameUrl("/a/b", "/a", at("/a"))).toBe(false)
    })

    it("percent-encoding is decoded the way route matching decodes it", () => {
      expect(isSameUrl("/tutors/amira%20h", "/", at("/tutors/amira h"))).toBe(true)
      expect(isSameUrl("/tutors/amira h", "/", at("/tutors/amira%20h"))).toBe(true)
      expect(isSameUrl("/tutors/a%2Fb", "/", at("/tutors/a/b"))).toBe(false)
      expect(isSameUrl("/tutors/%E0%A4%A", "/", at("/tutors/%E0%A4%A"))).toBe(true)
    })

    it("case stays significant: a param is another page", () => {
      expect(isSameUrl("/tutors/ABC", "/", at("/tutors/abc"))).toBe(false)
    })

    it("search stays exact", () => {
      expect(isSameUrl("/a?q=a%20b", "/a", at("/a", "?q=a b"))).toBe(false)
    })
  })
})
