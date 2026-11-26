import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import type { Crumb } from "@/components/ui/breadcrumbs"
import { backTarget } from "@/lib/nav/backTarget"
import { decideBackPlan, linkedParent, previousPathAt, recordHistoryLocation, type HistoryMemory } from "@/portals/student/backControl"
import { navGroups, studentShellTrail } from "@/portals/student/data"
import { STUDENT_BOTTOM_TABS } from "@/portals/student"

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

  it("no student route has a linked parent today", () => {
    // Guards the premise: if a lane adds a linked parent, this fails and the captures need a second look.
    const destinations = [...navGroups.flatMap((group) => group.items.map((item) => item.to)), ...STUDENT_BOTTOM_TABS.map((tab) => tab.to)]
    // Drilled-in pages are the likeliest to gain a linked parent, and no nav entry points at them.
    const drilledIn = ["/student/practice/papers", "/student/practice/result/1", "/student/plan/0580", "/student/sessions/1"]
    for (const p of [...destinations, ...drilledIn]) {
      expect(decideBackPlan({ trail: studentShellTrail(p), previousPath: null, hasHistory: false }), p).toEqual({ control: "bar" })
    }
  })
})

describe("committed history events", () => {
  // Each event is a committed router location: its key, the tab's history index, and the real location.pathname.
  type Event = [key: string, idx: number, pathname: string]
  const replay = (events: Event[], from: HistoryMemory = { key: null, idx: null, seen: new Map() }) =>
    events.reduce((state, [key, idx, pathname]) => recordHistoryLocation(state, { key, idx, pathname }), from)
  const planAt = (state: HistoryMemory) =>
    decideBackPlan({ trail: DRILL, previousPath: previousPathAt(state.seen, state.idx), hasHistory: true })

  it("push: the page pushed from is remembered, so the parent is named", () => {
    const state = replay([["a", 0, "/student/practice"], ["b", 1, "/student/detail"]])
    expect(planAt(state)).toMatchObject({ label: "Practice", action: "history" })
  })

  it("push from somewhere other than the parent: history, honestly labelled Back", () => {
    const state = replay([["a", 0, "/student/board"], ["b", 1, "/student/detail"]])
    expect(planAt(state)).toMatchObject({ label: "Back", action: "history" })
  })

  it("pop: returning to an earlier entry reads what that entry remembered", () => {
    const pushed = replay([["a", 0, "/student/practice"], ["b", 1, "/student/detail"], ["c", 2, "/student/board"]])
    expect(planAt(replay([["b", 1, "/student/detail"]], pushed))).toMatchObject({ label: "Practice" }) // pop back from c to b
    expect(planAt(replay([["c", 2, "/student/board"]], pushed))).toMatchObject({ label: "Back" }) // pop forward again
  })

  it("replace: the replaced entry's address is overwritten, so the next push names the new page", () => {
    const first = replay([["a", 0, "/student/board"]])
    const replaced = replay([["a2", 0, "/student/practice"]], first) // same idx, new key: a replace of the current entry
    expect(replaced.seen.get(0)).toBe("/student/practice")
    expect(planAt(replay([["b", 1, "/student/detail"]], replaced))).toMatchObject({ label: "Practice" })
    expect(planAt(replay([["b", 1, "/student/detail"]], first))).toMatchObject({ label: "Back" }) // without the replace
  })

  it("push after pop: the old forward entry at that index is overwritten", () => {
    const state = replay([
      ["a", 0, "/student/practice"], ["b", 1, "/student/board"], // forward entry
      ["a", 0, "/student/practice"], // pop to the start
      ["c", 1, "/student/detail"], // push a new page over the forward entry
    ])
    expect(state.seen.get(1)).toBe("/student/detail")
    expect(planAt(state)).toMatchObject({ label: "Practice" })
  })

  it("never mutates the memory it was given", () => {
    const first = replay([["a", 0, "/student/practice"]])
    const second = recordHistoryLocation(first, { key: "b", idx: 1, pathname: "/student/detail" })
    expect(second.seen).not.toBe(first.seen)
    expect(first.seen.has(1)).toBe(false)
  })

  it("reload: the entry index survives but the memory does not, so the label falls back to Back", () => {
    const afterReload = replay([["r", 1, "/student/detail"]]) // fresh memory, router still reports idx 1
    expect(afterReload.seen.get(0)).toBeUndefined()
    expect(planAt(afterReload)).toMatchObject({ label: "Back", action: "history" })
  })

  it("a dialog entry records its own URL, so going back from a page opened over it never names the page behind it", () => {
    // practice -> Settings dialog (location.pathname /student/settings, the page under it is still /student/practice) -> detail
    const state = replay([["a", 0, "/student/practice"], ["d", 1, "/student/settings"], ["b", 2, "/student/detail"]])
    expect(state.seen.get(1)).toBe("/student/settings")
    expect(planAt(state)).toMatchObject({ label: "Back", ariaLabel: "Back", action: "history" })
  })

  it("a dialog deep link has no earlier entry, so it never claims a parent", () => {
    const state = replay([["d", 0, "/student/settings"]])
    expect(planAt(state)).toMatchObject({ label: "Back" })
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
    expect(src).toMatch(/useStudentBackPlan\(location\.pathname, trail\)/)
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

describe("useStudentBackPlan wiring (backControl.ts)", () => {
  // No test renders the hook (vitest runs in node), so its body is guarded by source, like edgeSwipeBack.test.ts.
  const src = readFileSync(join(import.meta.dirname, "..", "..", "src", "portals", "student", "backControl.ts"), "utf8")
  const start = src.indexOf("export function useStudentBackPlan(")
  const hook = src.slice(start, src.indexOf("\n}\n", start) + 2)
  const effect = hook.match(/useLayoutEffect\(\(\) => \{[\s\S]*?\n {2}\}, \[key, pathname\]\)/)?.[0] ?? ""
  const render = effect === "" ? hook : hook.replace(effect, "")

  it("finds the hook body", () => {
    expect(start).toBeGreaterThan(-1)
    expect(hook).toMatch(/^export function useStudentBackPlan\(pathname: string, trail: readonly Crumb\[\]\): BackPlan \{/)
    expect(hook).toMatch(/\n\}$/)
  })

  it("records the committed location in a layout effect keyed on the router's location key, so no frame shows the stale label", () => {
    expect(hook).toMatch(/const \{ key \} = useLocation\(\)/)
    expect(effect).toMatch(/^useLayoutEffect\(/)
    expect(effect).toContain("record({ key, idx: currentHistoryIdx(), pathname })")
    expect(hook).not.toMatch(/\buseEffect\(/)
  })

  it("until the current key is recorded the plan is the plain Back, never a guessed parent", () => {
    expect(hook).toMatch(/const committed = history\.key === key\b/)
    expect(hook).toMatch(/previousPath: committed \? previousPathAt\(history\.seen, history\.idx\) : null/)
    expect(hook).toMatch(/hasHistory: !committed \|\|/)
  })

  it("never reads window.history.state while rendering: the index is read only inside the effect", () => {
    expect(render).not.toMatch(/window\.history|\bhistory\.state\b/)
    expect(render).not.toContain("currentHistoryIdx")
    expect(effect).toContain("currentHistoryIdx()")
  })
})
