import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { BottomNav } from "@/components/ui/nav-shells"
import { STUDENT_BOTTOM_TABS } from "@/portals/student"
import { isPlanSection, isPracticeSection, studentOverflowItems } from "@/portals/student/shellNav"

const SRC = join(fileURLToPath(new URL("../../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("student tab bar (mock h6.js TAB6, Plan in the Subjects slot by user ruling)", () => {
  it("is Home, Practice, Scan, Plan, Me, with Scan in the centre", () => {
    expect(STUDENT_BOTTOM_TABS.map((t) => t.label)).toEqual(["Home", "Practice", "Scan a paper", "Plan", "Me"])
    expect(STUDENT_BOTTOM_TABS[2]).toMatchObject({ id: "scan", to: "/student/correct" })
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "practice")?.to).toBe("/student/practice")
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "plan")?.to).toBe("/student/plan")
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "me")?.to).toBe("/student/profile")
    // The Subjects tab and its sheet-opening machinery are gone.
    expect(STUDENT_BOTTOM_TABS.some((t) => "opensNav" in t)).toBe(false)
    expect(STUDENT_BOTTOM_TABS.some((t) => t.label === "Subjects")).toBe(false)
  })

  it("has no appended More cell for the student bar; the shell still offers it to teacher and parent", () => {
    expect(read("portals/student/shell.tsx")).toContain("moreTab={false}")
    const portal = read("components/shell/PortalShell.tsx")
    expect(portal).toMatch(/moreTab\?: boolean/)
    expect(portal).not.toMatch(/navTabId/)
  })

  it("Practice covers practice and flashcards; Plan covers the study plan", () => {
    for (const p of ["/student/practice", "/student/practice/0580", "/student/practice/set/a1", "/student/flashcards/0580", "/student/flashcards/review/0580"])
      expect(isPracticeSection(p), p).toBe(true)
    expect(isPracticeSection("/student/practiced")).toBe(false)
    for (const p of ["/student/plan", "/student/plan/0580", "/student/plan/0580/session/s1"]) expect(isPlanSection(p), p).toBe(true)
    expect(isPlanSection("/student/planner")).toBe(false)
    expect(isPlanSection("/student")).toBe(false)
  })

  it("every old sidebar destination except Overview lands in the More group", () => {
    const items = [{ to: "/student" }, { to: "/student/classes" }, { to: "/student/board" }]
    expect(studentOverflowItems(items)).toEqual([{ to: "/student/classes" }, { to: "/student/board" }])
    expect(read("portals/student/shell.tsx")).toMatch(/label: "More"/)
  })

  it("mounts /student/practice and /student/plan as the interim entries", () => {
    const index = read("portals/student/index.tsx")
    expect(index).toMatch(/path: "practice",\s*element: <PracticeEntry \/>/)
    expect(index).toMatch(/path: "plan",\s*element: <PlanEntry \/>/)
  })

  it("the raised tab is a soft Tide squircle with a visually hidden label", () => {
    const out = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(BottomNav, {
          items: [{ id: "scan", label: "Scan a paper", to: "/student/correct", icon: createElement("svg") }],
          emphasisId: "scan",
        }),
      ),
    )
    expect(out).toMatch(/data-emphasis="true"[^>]*class="[^"]*\bh-14 w-14 rounded-tile bg-inverse-primary text-primary\b/)
    expect(out).toMatch(/class="lm-native-tab-label text-xs sr-only">Scan a paper</)
  })

  it("the rail foot and the tablet bar say Scan a paper with the camera, outlined", () => {
    const shell = read("portals/student/shell.tsx")
    expect(shell).toContain("SHELL_BUTTON_OUTLINE")
    expect(shell).toContain('<ShellIcon name="cam" />')
    expect(shell).toContain("<span>Scan a paper</span>")
    expect(shell).toMatch(/scan\("me-2\.5 max-shell-sm:hidden shell-lg:hidden"\)/)
    expect(shell).not.toContain("Upload a paper")
  })

  it("keeps the subject tree and the More group in the sidebar (every old row stays reachable)", () => {
    const shell = read("portals/student/shell.tsx")
    expect(shell).toMatch(/id: "subjects"/)
    expect(shell).toMatch(/id: "more"/)
    expect(shell).toContain("studentOverflowItems(navItems)")
  })
})
