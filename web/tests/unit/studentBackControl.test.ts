import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import type { Crumb } from "@/components/ui/breadcrumbs"
import { backTarget } from "@/lib/nav/backTarget"
import { decideBackPlan, linkedParent, previousPathAt } from "@/portals/student/backControl"
import { studentShellTrail } from "@/portals/student/data"

// develop has no student route with a linked parent yet (lanes add them), so the rule is exercised on fixture trails.
const DRILL: Crumb[] = [{ label: "Practice", to: "/student/practice" }, { label: "Past papers" }]
const DEEP: Crumb[] = [{ label: "Subject", to: "/student/subject/0580" }, { label: "Practice", to: "/student/practice/0580" }, { label: "Result" }]

describe("linkedParent", () => {
  it("is the nearest linked ancestor, skipping unlinked grouping crumbs", () => {
    expect(linkedParent(DRILL)).toEqual({ label: "Practice", to: "/student/practice" })
    expect(linkedParent(DEEP)?.label).toBe("Practice")
    expect(linkedParent([{ label: "Subject", to: "/student/subject/0580" }, { label: "Group" }, { label: "Page" }])?.label).toBe("Subject")
  })
  it("is null with no linked ancestor, and for a root page", () => {
    expect(linkedParent([{ label: "Practice" }, { label: "0580" }])).toBeNull()
    expect(linkedParent([{ label: "Overview" }])).toBeNull()
    expect(linkedParent([])).toBeNull()
  })
  it("never counts the current page, even when it is linked", () => {
    expect(linkedParent([{ label: "Practice" }, { label: "0580", to: "/student/practice/0580" }])).toBeNull()
  })
})

describe("decideBackPlan", () => {
  it("parent is the previous page: goes back through history, labelled with the parent", () => {
    expect(decideBackPlan({ trail: DRILL, previousPath: "/student/practice", hasHistory: true })).toEqual({
      control: "trail",
      action: "history",
      label: "Practice",
      ariaLabel: "Back to Practice",
      parentTo: "/student/practice",
    })
  })

  it("compares paths, not strings: a trailing slash, query or hash on the previous page still is the parent", () => {
    for (const previousPath of ["/student/practice/", "/student/practice?tab=a", "/student/practice#x"]) {
      const plan = decideBackPlan({ trail: DRILL, previousPath, hasHistory: true })
      expect(plan).toMatchObject({ control: "trail", label: "Practice" })
    }
  })

  it("previous page is elsewhere: still history, honestly labelled Back", () => {
    expect(decideBackPlan({ trail: DRILL, previousPath: "/student", hasHistory: true })).toEqual({
      control: "trail",
      action: "history",
      label: "Back",
      ariaLabel: "Back",
      parentTo: "/student/practice",
    })
    // A prefix of the parent's path is not the parent.
    expect(decideBackPlan({ trail: DRILL, previousPath: "/student/practice/0580", hasHistory: true })).toMatchObject({ label: "Back" })
  })

  it("history exists but the previous page is unknown (after a reload): history, labelled Back", () => {
    expect(decideBackPlan({ trail: DRILL, previousPath: null, hasHistory: true })).toMatchObject({ action: "history", label: "Back", ariaLabel: "Back" })
  })

  it("deep link, no history: goes to the parent, labelled with it", () => {
    expect(decideBackPlan({ trail: DRILL, previousPath: null, hasHistory: false })).toEqual({
      control: "trail",
      action: "route",
      label: "Practice",
      ariaLabel: "Back to Practice",
      parentTo: "/student/practice",
    })
    // A stale previous path does not matter without history.
    expect(decideBackPlan({ trail: DRILL, previousPath: "/student", hasHistory: false })).toMatchObject({ action: "route", label: "Practice" })
  })

  it("trail without a linked parent keeps today's controls", () => {
    for (const hasHistory of [true, false]) {
      expect(decideBackPlan({ trail: [{ label: "Practice" }, { label: "0580" }], previousPath: "/student", hasHistory })).toEqual({ control: "bar" })
    }
  })

  it("root pages (one crumb or none) keep today's controls", () => {
    expect(decideBackPlan({ trail: [{ label: "Overview" }], previousPath: null, hasHistory: false })).toEqual({ control: "bar" })
    expect(decideBackPlan({ trail: [], previousPath: null, hasHistory: false })).toEqual({ control: "bar" })
  })

  it("uses the nearest linked ancestor of a deeper trail", () => {
    expect(decideBackPlan({ trail: DEEP, previousPath: "/student/practice/0580", hasHistory: true })).toMatchObject({ label: "Practice", action: "history" })
  })

  it("every student route on develop still resolves, with no linked parent today", () => {
    // Guards the premise: if a lane adds a linked parent, this fails and the captures need a second look.
    const paths = ["/student/practice/papers", "/student/practice/result/1", "/student/plan/0580", "/student/sessions/1"]
    for (const p of paths) expect(decideBackPlan({ trail: studentShellTrail(p), previousPath: null, hasHistory: false })).toEqual({ control: "bar" })
  })
})

describe("in-app previous page by history index", () => {
  it("reads the page one entry back, whatever was pushed, popped or replaced since", () => {
    const seen = new Map<number, string>()
    seen.set(0, "/student")
    seen.set(1, "/student/practice")
    seen.set(2, "/student/practice/papers")
    expect(previousPathAt(seen, 2)).toBe("/student/practice")
    // Back to idx 1: the previous is idx 0, not the page just left.
    expect(previousPathAt(seen, 1)).toBe("/student")
    // A push after that overwrites idx 2.
    seen.set(2, "/student/practice/result/9")
    expect(previousPathAt(seen, 2)).toBe("/student/practice")
  })
  it("is unknown at the first entry, outside a browser, and for an entry this tab never recorded", () => {
    const seen = new Map<number, string>([[3, "/student"]])
    expect(previousPathAt(seen, 0)).toBeNull()
    expect(previousPathAt(seen, null)).toBeNull()
    expect(previousPathAt(seen, 3)).toBeNull()
  })
  it("agrees with backTarget on what counts as history", () => {
    expect(backTarget(0, "/student").kind).toBe("route")
    expect(backTarget(undefined, "/student").kind).toBe("route")
    expect(backTarget(2, "/student").kind).toBe("history")
  })
})

describe("student shell wiring (shell.tsx)", () => {
  const src = readFileSync(join(import.meta.dirname, "..", "..", "src", "portals", "student", "shell.tsx"), "utf8")

  it("derives the plan from the trail and hands the top bar a history-or-parent action", () => {
    expect(src).toMatch(/useStudentBackPlan\(pagePath, trail\)/)
    expect(src).toMatch(/useBackAction\(backPlan\.control === "trail" \? backPlan\.parentTo : "\/student"\)/)
    expect(src).toMatch(/trailBack:\s*titleLevel === "detail" && backPlan\.control === "trail"/)
    expect(src).toMatch(/onActivate: goBack/)
    expect(src).toMatch(/ariaLabel: backPlan\.ariaLabel/)
  })

  it("hides the bar's Back below sm only when the trail carries the control, and never for a trail without a linked parent", () => {
    expect(src).toMatch(/backPlan\.control === "trail" && "max-sm:hidden"/)
    // The default class set is unchanged, so a page without a linked parent keeps today's markup.
    expect(src).toMatch(/cn\("shell-lg:hidden native:hidden", backPlan\.control === "trail"/)
  })

  it("keeps no route list: the rule reads the trail only", () => {
    const helper = readFileSync(join(import.meta.dirname, "..", "..", "src", "portals", "student", "backControl.ts"), "utf8")
    expect(helper).not.toMatch(/\/student\//)
  })
})
