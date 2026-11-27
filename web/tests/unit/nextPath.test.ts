import { describe, expect, it } from "vitest"
import { safeNextPath, withNext } from "@/lib/nextPath"

/*
 * PR 2 part A2 · the `?next=` open-redirect guard, pinned.
 *
 * Every reject case below is a real shape an attacker (or a careless copy of
 * `window.location.href`) could hand this function via a query parameter —
 * see `lib/nextPath.ts`'s own module doc for why each one is dangerous.
 */

describe("safeNextPath", () => {
  it("accepts a same-origin absolute path", () => {
    expect(safeNextPath("/student/board")).toBe("/student/board")
  })

  it("accepts a same-origin path with a query string", () => {
    expect(safeNextPath("/student/board?x=1")).toBe("/student/board?x=1")
  })

  it("returns null for a bare null (no ?next= at all)", () => {
    expect(safeNextPath(null)).toBeNull()
  })

  it("returns null for an empty string", () => {
    expect(safeNextPath("")).toBeNull()
  })

  it("rejects a protocol-relative URL (//evil.example)", () => {
    expect(safeNextPath("//evil.example")).toBeNull()
  })

  it("rejects a backslash-prefixed path (/\\evil.example)", () => {
    expect(safeNextPath("/\\evil.example")).toBeNull()
  })

  it("rejects an absolute URL with a scheme", () => {
    expect(safeNextPath("https://evil.example")).toBeNull()
    expect(safeNextPath("http://evil.example/x")).toBeNull()
  })

  it("rejects a javascript: URL", () => {
    expect(safeNextPath("javascript:alert(1)")).toBeNull()
  })

  it("rejects a relative path with no leading slash", () => {
    expect(safeNextPath("student/board")).toBeNull()
    expect(safeNextPath("evil.example")).toBeNull()
  })

  it("rejects a path longer than 500 characters", () => {
    const long = "/" + "a".repeat(500)
    expect(long.length).toBeGreaterThan(500)
    expect(safeNextPath(long)).toBeNull()
  })

  it("accepts a path at exactly the 500-character ceiling", () => {
    const atLimit = "/" + "a".repeat(499)
    expect(atLimit.length).toBe(500)
    expect(safeNextPath(atLimit)).toBe(atLimit)
  })

  it("rejects a path containing whitespace", () => {
    expect(safeNextPath("/student /board")).toBeNull()
    expect(safeNextPath(" /student")).toBeNull()
    expect(safeNextPath("/student\t/board")).toBeNull()
    expect(safeNextPath("/student\n/board")).toBeNull()
  })

  it("rejects a path containing a control character", () => {
    expect(safeNextPath("/student\u0000/board")).toBeNull()
    expect(safeNextPath("/student\u007f/board")).toBeNull()
  })

  it("does not rewrite or strip anything from an accepted value", () => {
    const value = "/student/subject/0625?tab=practice&x=1"
    expect(safeNextPath(value)).toBe(value)
  })
})

describe("withNext", () => {
  it("returns the base unchanged when next is null", () => {
    expect(withNext("/login", null)).toBe("/login")
  })

  it("appends an encoded ?next= when next is present", () => {
    expect(withNext("/login", "/student/board")).toBe("/login?next=%2Fstudent%2Fboard")
  })

  it("encodes a query string inside next so it does not merge with the outer one", () => {
    expect(withNext("/login", "/student/board?x=1")).toBe(
      "/login?next=%2Fstudent%2Fboard%3Fx%3D1",
    )
  })
})

describe("safeNextPath hardening", () => {
  it("still accepts real in-app paths", () => {
    for (const ok of [
      "/teacher/billing/plans?plan=teacher_pro_m&interval=month",
      "/student/billing#plans",
      "/a?x=%2Fb",
      "/a?x=%5Cb",
      "/student",
    ]) {
      expect(safeNextPath(ok), ok).toBe(ok)
    }
  })
  it("rejects a backslash anywhere, not only at the start", () => {
    expect(safeNextPath("/a\\b")).toBeNull()
  })
  it("rejects scheme-only vectors", () => {
    expect(safeNextPath("javascript:alert(1)")).toBeNull()
    expect(safeNextPath("data:text/html,x")).toBeNull()
  })
})
