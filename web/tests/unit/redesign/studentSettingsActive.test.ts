import { describe, expect, it } from "vitest"
import { underDialogActive } from "@/portals/student/shellNav"

/* Settings is a dialog route (/student/settings) over the page it was opened from. A fresh load has no
 * underlying page, so the shell falls back to /student. The sidebar must light the row for that page,
 * not none. */
describe("sidebar rows under the Settings dialog", () => {
  const HOME = { to: "/student", end: true }
  const ME = { to: "/student/profile" }
  const PRACTICE = { to: "/student/practice" }

  it("fresh load of /student/settings lights Home, nothing else", () => {
    expect(underDialogActive(HOME, "/student", "/student/settings")).toBe(true)
    expect(underDialogActive(ME, "/student", "/student/settings")).toBeUndefined()
    expect(underDialogActive(PRACTICE, "/student", "/student/settings")).toBeUndefined()
  })
  it("opened over Me, Me is lit and Home is not", () => {
    expect(underDialogActive(ME, "/student/profile", "/student/settings")).toBe(true)
    expect(underDialogActive(HOME, "/student/profile", "/student/settings")).toBeUndefined()
  })
  it("with no dialog open it leaves the row to its own NavLink match", () => {
    expect(underDialogActive(HOME, "/student", "/student")).toBeUndefined()
    expect(underDialogActive(ME, "/student/profile", "/student/profile")).toBeUndefined()
  })
})

describe("the student shell wires it", () => {
  it("every primary sidebar row asks underDialogActive", async () => {
    const { readFileSync } = await import("node:fs")
    const src = readFileSync(new URL("../../../src/portals/student/shell.tsx", import.meta.url), "utf8")
    expect(src).toContain("underDialogActive({ to, end }, pagePath, location.pathname)")
    expect(src.match(/active: [^}]*under\(/g)).toHaveLength(4)
  })
})
