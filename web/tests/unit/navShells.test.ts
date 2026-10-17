import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { BOTTOM_NAV_HEIGHT, SIDEBAR_BREAKPOINT, SIDEBAR_WIDTH } from "@/components/ui/nav-shells"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B3 (Task 4) · the shell primitives' retrofit. `nav-shells.tsx`'s own
 * header used to say the route wiring was future work ("stays in the kit
 * unused for now") — this pins that it no longer is: `NavShellItem` wires
 * through react-router's `NavLink`, and every portal's chrome actually mounts
 * `BottomNav`/`SidebarNav` rather than a bespoke copy.
 */

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

function read(relPath: string): string {
  return readFileSync(join(SRC, relPath), "utf8")
}

describe("sidebar/bottom-nav constants agree with index.css", () => {
  it("SIDEBAR_WIDTH is 252", () => {
    expect(SIDEBAR_WIDTH).toBe(252)
  })

  it("SIDEBAR_BREAKPOINT is 820", () => {
    expect(SIDEBAR_BREAKPOINT).toBe(820)
  })

  it("BOTTOM_NAV_HEIGHT is 56", () => {
    expect(BOTTOM_NAV_HEIGHT).toBe(56)
  })
})

describe("nav-shells.tsx wires NavShellItem through react-router", () => {
  const source = stripComments(read("components/ui/nav-shells.tsx"))

  it("imports NavLink", () => {
    expect(source).toMatch(/import\s*\{[^}]*\bNavLink\b[^}]*\}\s*from\s*"react-router-dom"/)
  })

  it("passes viewTransition on the router-wired link", () => {
    expect(source).toContain("viewTransition")
  })

  it("no longer describes the wiring as pending", () => {
    expect(read("components/ui/nav-shells.tsx")).not.toContain("stays in the kit unused")
  })
})

describe("every portal shell imports SidebarNav", () => {
  const PORTALS = ["portals/student/index.tsx", "portals/teacher/index.tsx", "portals/admin/index.tsx"]

  it.each(PORTALS)("%s imports SidebarNav", (file) => {
    const source = read(file)
    expect(source).toMatch(/import\s*\{[^}]*\bSidebarNav\b[^}]*\}\s*from\s*"@\/components\/ui\/nav-shells"/)
  })
})

describe("student and teacher shells mount BottomNav with the five labels in order", () => {
  it("student/index.tsx imports BottomNav and orders its five tabs", () => {
    const source = stripComments(read("portals/student/index.tsx"))
    expect(source).toMatch(/import\s*\{[^}]*\bBottomNav\b[^}]*\}\s*from\s*"@\/components\/ui\/nav-shells"/)
    expect(source).toMatch(
      /"Overview"[\s\S]*"Correct"[\s\S]*"Classes"[\s\S]*"Profile"[\s\S]*"More"/,
    )
  })

  it("teacher/index.tsx imports BottomNav and orders its five tabs", () => {
    const source = stripComments(read("portals/teacher/index.tsx"))
    expect(source).toMatch(/import\s*\{[^}]*\bBottomNav\b[^}]*\}\s*from\s*"@\/components\/ui\/nav-shells"/)
    expect(source).toMatch(
      /"Overview"[\s\S]*"Grading"[\s\S]*"Review"[\s\S]*"Classes"[\s\S]*"More"/,
    )
  })
})
