import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { imageFailedFor } from "@/lib/hooks/useTeacherApi"
import { pageFrame } from "@/portals/teacher/screens/review/useAnswerImages"

/*
 * A whole page that fails (404/422 from the route, or bytes that will not
 * decode) used to leave the panel on "Loading the page" for good: the image
 * hook reported loading and failure both as `url: null`, and the panel read
 * `pageRequested && !pageUrl` as loading.
 */
const REVIEW = path.resolve(import.meta.dirname, "../../src/portals/teacher/screens/review")
const read = (f: string) => readFileSync(path.join(REVIEW, f), "utf8")

describe("whole-page frame", () => {
  it("shows the page once it has a URL", () => {
    expect(pageFrame({ pageUrl: "blob:x", pageRequested: true, pageFailed: false })).toBe("image")
  })
  it("shows loading while the requested page has neither a URL nor a failure", () => {
    expect(pageFrame({ pageUrl: null, pageRequested: true, pageFailed: false })).toBe("loading")
  })
  it("shows the failure, not an endless skeleton, once the page failed", () => {
    expect(pageFrame({ pageUrl: null, pageRequested: true, pageFailed: true })).toBe("failed")
  })
  it("calls a page nobody has asked for yet idle, never failed", () => {
    expect(pageFrame({ pageUrl: null, pageRequested: false, pageFailed: false })).toBe("idle")
  })
  it("reports a recorded failure even before the request flag catches up", () => {
    expect(pageFrame({ pageUrl: null, pageRequested: false, pageFailed: true })).toBe("failed")
  })
})

describe("image failure identity", () => {
  it("marks only the item the failure was recorded for", () => {
    expect(imageFailedFor("a", "a")).toBe(true)
    expect(imageFailedFor("b", "a")).toBe(false)
    expect(imageFailedFor("a", null)).toBe(false)
    expect(imageFailedFor(undefined, null)).toBe(false)
  })
})

describe("wiring", () => {
  it("passes the page hook's failure to the panel", () => {
    expect(read("useAnswerImages.ts")).toMatch(/pageFailed: page\.failed/)
  })
  it("decides the whole-page frame with pageFrame, not pageRequested alone", () => {
    const src = read("AnswerPanel.tsx")
    expect(src).toMatch(/const wholePage = showPage \? pageFrame\(images\) : null/)
    expect(src).toMatch(/wholePage === "failed"/)
    // An idle page tab asks for its page instead of claiming it failed.
    expect(src).toMatch(/if \(wholePage === "idle"\) requestPage\(\)/)
    expect(src).not.toMatch(/\) : images\.pageRequested \?/)
  })
})
